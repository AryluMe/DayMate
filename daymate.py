from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
import threading
import time
import traceback
import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time as day_time, timedelta

import browser_history
import ctypes
from ctypes import wintypes
from pathlib import Path
from typing import Any, Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_RULES_PATH = SCRIPT_DIR / "rules.yaml"
TASK_NAME = "DayMateActivityTracker"
CURRENT_STATE_SCHEMA_VERSION = 2
CURRENT_STATE_HEARTBEAT_SECONDS = 30.0
CURRENT_STATE_CATEGORY_ORDER = ["coding", "browsing", "gaming", "chat", "other", "away"]

# ── v2: process-level tracking ──
TOOL_MAP: dict[str, dict[str, str]] = {
    "assistant.exe": {"id": "assistant", "label": "Assistant", "category": "coding"},
    "editor.exe": {"id": "editor", "label": "Editor", "category": "coding"},
    "terminal.exe": {"id": "terminal", "label": "Terminal", "category": "coding"},
    "browser.exe": {"id": "browser", "label": "Browser", "category": "browsing"},
    "chat-client.exe": {"id": "chat", "label": "Chat", "category": "chat"},
    "game.exe": {"id": "game", "label": "Game", "category": "gaming"},
    "game-launcher.exe": {"id": "game-launcher", "label": "Game Launcher", "category": "gaming"},
    "file-manager.exe": {"id": "file-manager", "label": "File Manager", "category": "other"},
    "python.exe": {"id": "python", "label": "Python", "category": "coding"},
    "pythonw.exe": {"id": "pythonw", "label": "Python", "category": "coding"},
}
TOOL_IDS = {"assistant", "editor", "terminal", "browser", "chat", "game", "game-launcher", "file-manager", "python", "pythonw"}

_TASK_RE = re.compile(r"T(\d{1,3})\s*[-\u2013\u2014]\s*(.+)")
_TASK_BARE_RE = re.compile(r"\bT(\d{1,3})\b")
_PATH_RE = re.compile(r"[A-Za-z]:[\\/][^\s]*")
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def extract_task_hint(title: str) -> str | None:
    """Extract task hint like 'T33 - 基金' from window title."""
    m = _TASK_RE.search(title)
    if m:
        num = m.group(1)
        desc = m.group(2).strip()
        if len(desc) > 60:
            desc = desc[:57] + "..."
        return f"T{num} - {desc}"
    m = _TASK_BARE_RE.search(title)
    if m:
        return f"T{m.group(1)}"
    return None


def sanitize_title(title: str) -> str:
    """Sanitize window title: remove paths, UUIDs, and truncate."""
    if not title:
        return ""
    t = _PATH_RE.sub("", title)
    t = _UUID_RE.sub("", t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > 100:
        t = t[:97] + "..."
    return t


def now_local() -> datetime:
    return datetime.now().replace(microsecond=0)


def parse_date(value: str | None) -> date:
    if not value:
        return now_local().date()
    return datetime.strptime(value, "%Y-%m-%d").date()


def default_data_root() -> Path:
    return Path.home() / ".daymate" / "data"


def empty_keyboard_stats() -> dict[str, int]:
    return {
        "total_keys": 0,
        "letters": 0,
        "numbers": 0,
        "function_keys": 0,
        "direction_keys": 0,
        "modifier_keys": 0,
        "wasd_keys": 0,
        "delete_keys": 0,
    }


def counter_to_keyboard_stats(counter: Counter[str]) -> dict[str, int]:
    stats = empty_keyboard_stats()
    for key in stats:
        stats[key] = int(counter.get(key, 0))
    return stats


@dataclass(frozen=True)
class WindowInfo:
    title: str
    process_name: str
    exe_path: str = ""

    def key(self) -> tuple[str, str]:
        return (self.process_name.lower(), self.title)


@dataclass
class SegmentState:
    segment_id: str
    start_ts: datetime
    window: WindowInfo
    tags: list[str]
    keyboard_snapshot: Counter[str]
    is_away: bool = False


# ── PollingKeyboardTracker: replaces pynput keyboard hooks ──
# Uses GetLastInputInfo (zero-hook idle detection) + GetKeyboardState polling.
# All work runs inside the existing 2-second poll loop, not on every keystroke.
# This eliminates the WH_KEYBOARD_LL hook that was causing input latency.
#
# AdaptiveKeyCompensator (v2): models rolling typing profile and fills gaps when
# detected keys fall below predicted rate — compensates for fast typists whose
# key-down→key-up fits entirely inside one 2s poll window.

from collections import deque
import statistics

_VK_LETTER_START = 0x41
_VK_LETTER_END = 0x5A
_VK_NUMBER_START = 0x30
_VK_NUMBER_END = 0x39
_VK_FUNC_START = 0x70
_VK_FUNC_END = 0x87
_VK_W = 0x57
_VK_A = 0x41
_VK_S = 0x53
_VK_D = 0x44
_VK_LEFT = 0x25
_VK_UP = 0x26
_VK_RIGHT = 0x27
_VK_DOWN = 0x28
_VK_BACK = 0x08
_VK_DELETE = 0x2E
_MODIFIER_VKS = frozenset({
    0x10, 0x11, 0x12,          # Shift, Ctrl, Alt
    0xA0, 0xA1,                # L/R Shift
    0xA2, 0xA3,                # L/R Ctrl
    0xA4, 0xA5,                # L/R Alt
    0x14,                      # Caps Lock
    0x5B, 0x5C,                # L/R Win
})

# Compensation tunables
_COMP_WINDOW_SECONDS = 300.0    # rolling profile window (~5 min)
_COMP_MIN_SAMPLES = 5            # need at least this many intervals to build profile
_COMP_GAP_RATIO = 0.5            # trigger comp when detected < profile * this
_COMP_DAMPING = 0.7              # dampening factor (0=ignore, 1=fully trust profile)
_COMP_MAX_BOOST = 4.0            # cap compensation multiplier


class _LASTINPUTINFO(ctypes.Structure):
    _fields = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


class AdaptiveKeyCompensator:
    """Models user typing profile from detected keys and compensates for sampling gaps.

    Principle: even with 2s polling we *do* detect some keys every cycle — enough
    to estimate true typing rate. When GetLastInputInfo confirms active typing but
    detected count is below profile, we fill the gap with proportional compensation.
    """

    def __init__(self):
        # Rolling window: (interval_seconds, total_keys_detected, category_counts)
        self._window: deque[tuple[float, int, dict[str, int]]] = deque()
        self._lock = threading.Lock()

    def record(self, interval_sec: float, detected: Counter[str]) -> None:
        """Record a poll interval's detection result into the rolling window."""
        if interval_sec <= 0:
            return
        cat = {}
        for k in ("letters", "numbers", "function_keys", "direction_keys", "modifier_keys", "delete_keys", "wasd_keys"):
            cat[k] = int(detected.get(k, 0))
        entry = (interval_sec, int(detected.get("total_keys", 0)), cat)
        with self._lock:
            self._window.append(entry)
            # Evict old entries
            total_age = 0.0
            while self._window and total_age + self._window[0][0] > _COMP_WINDOW_SECONDS:
                total_age += self._window[0][0]
            while self._window:
                s = sum(e[0] for e in self._window)
                if s <= _COMP_WINDOW_SECONDS:
                    break
                self._window.popleft()

    def compensate(self, interval_sec: float, detected: Counter[str]) -> Counter[str]:
        """Return compensated counts. If profile is immature or detected is close to
        predicted, returns detected as-is."""
        with self._lock:
            if len(self._window) < _COMP_MIN_SAMPLES:
                return Counter(detected)

            # Profile stats from window
            recent = list(self._window)

        total_detected = sum(e[1] for e in recent)
        total_interval = sum(e[0] for e in recent)
        if total_interval <= 0 or total_detected == 0:
            return Counter(detected)

        # Build category ratio profile (from all detected keys)
        cat_totals: dict[str, float] = {}
        for _, _, cats in recent:
            for k, v in cats.items():
                cat_totals[k] = cat_totals.get(k, 0.0) + v

        profile_kps = total_detected / total_interval
        detected_kps = detected.get("total_keys", 0) / interval_sec if interval_sec > 0 else 0

        # Trigger: detected significantly below profile while actively typing
        if profile_kps <= 0 or detected_kps >= profile_kps * _COMP_GAP_RATIO:
            return Counter(detected)

        # Gap = how many keys we probably missed
        expected = profile_kps * interval_sec
        gap = expected - detected.get("total_keys", 0)
        gap = min(gap, profile_kps * interval_sec * _COMP_MAX_BOOST)  # cap
        gap *= _COMP_DAMPING
        if gap < 1:
            return Counter(detected)

        # Distribute gap across categories proportional to profile
        result = Counter(detected)
        for cat, cat_total in cat_totals.items():
            ratio = cat_total / total_detected if total_detected > 0 else 0
            compensated = int(round(gap * ratio))
            if compensated > 0:
                result[cat] = result.get(cat, 0) + compensated
        result["total_keys"] = result.get("total_keys", 0) + int(round(gap))
        return result


class PollingKeyboardTracker:
    """Keyboard idle detection + key counting — all via polling, no global hooks."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counts: Counter[str] = Counter()
        self._last_key_ts = now_local()
        self._prev_state: tuple[int, ...] | None = None
        self._user32 = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32
        self._compensator = AdaptiveKeyCompensator()
        self._last_poll_ts: datetime | None = None

    def start(self) -> None:
        """No-op: polling tracker doesn't need a listener thread."""
        self._last_key_ts = now_local()
        self._last_poll_ts = None

    def stop(self) -> None:
        """No-op."""

    def poll(self) -> None:
        """Call once per poll cycle (~2s). Updates idle ts + key counts via state diff."""
        now = now_local()
        try:
            # Idle detection via GetLastInputInfo
            lii = _LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
            active_now = False
            if self._user32.GetLastInputInfo(ctypes.byref(lii)):
                uptime_ms = self._kernel32.GetTickCount64()
                idle_ms = uptime_ms - lii.dwTime
                self._last_key_ts = now - timedelta(milliseconds=max(0, idle_ms))
                active_now = idle_ms < 2000  # user touched input in this interval

            # Key counting via GetKeyboardState diff
            import win32api
            new_state = win32api.GetKeyboardState()
            if self._prev_state is not None:
                self._count_keys_diff(self._prev_state, new_state, now, active_now)
            self._prev_state = new_state
        except Exception:
            pass

    def _count_keys_diff(
        self, prev: tuple[int, ...], curr: tuple[int, ...], now: datetime, active_now: bool
    ) -> None:
        """Detect newly-pressed keys and apply adaptive compensation."""
        updates: Counter[str] = Counter()
        for vk in range(256):
            was_down = bool(prev[vk] & 0x80)
            is_down = bool(curr[vk] & 0x80)
            if is_down and not was_down:
                updates["total_keys"] += 1
                if _VK_LETTER_START <= vk <= _VK_LETTER_END:
                    updates["letters"] += 1
                    if vk in (_VK_W, _VK_A, _VK_S, _VK_D):
                        updates["wasd_keys"] += 1
                elif _VK_NUMBER_START <= vk <= _VK_NUMBER_END:
                    updates["numbers"] += 1
                elif _VK_FUNC_START <= vk <= _VK_FUNC_END:
                    updates["function_keys"] += 1
                if vk in (_VK_LEFT, _VK_UP, _VK_RIGHT, _VK_DOWN):
                    updates["direction_keys"] += 1
                if vk in (_VK_BACK, _VK_DELETE):
                    updates["delete_keys"] += 1
                if vk in _MODIFIER_VKS:
                    updates["modifier_keys"] += 1

        # Adaptive compensation: feed detected → profile, then compensate if gap exists
        if self._last_poll_ts is not None:
            interval_sec = (now - self._last_poll_ts).total_seconds()
            if updates["total_keys"] > 0 or active_now:
                self._compensator.record(interval_sec, updates)
            compensated = self._compensator.compensate(interval_sec, updates)
            updates = compensated
        self._last_poll_ts = now

        if updates and updates["total_keys"] > 0:
            with self._lock:
                self._counts.update(updates)

    def snapshot(self) -> Counter[str]:
        with self._lock:
            return Counter(self._counts)

    def last_key_ts(self) -> datetime:
        with self._lock:
            return self._last_key_ts

    def diff_since(self, snapshot: Counter[str]) -> Counter[str]:
        with self._lock:
            current = Counter(self._counts)
        diff: Counter[str] = Counter()
        for key in empty_keyboard_stats():
            diff[key] = max(0, current.get(key, 0) - snapshot.get(key, 0))
        return diff


class RuleEngine:
    def __init__(self, rules_path: Path):
        self.rules_path = rules_path
        self.default_tag = "other"
        self.rules: list[dict[str, Any]] = []
        self.load()

    def load(self) -> None:
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError("Missing dependency PyYAML. Run: pip install -r requirements.txt") from exc

        if not self.rules_path.exists():
            self.rules = []
            return

        with self.rules_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}

        self.default_tag = str(data.get("default_tag") or "other")
        raw_rules = data.get("rules") or []
        self.rules = [rule for rule in raw_rules if isinstance(rule, dict)]

    def match(self, window: WindowInfo) -> list[str]:
        process = window.process_name.lower()
        title = window.title.lower()
        best_rule: dict[str, Any] | None = None
        best_score = -1

        for rule in self.rules:
            pattern = str(rule.get("process") or "*").lower()
            if not fnmatch.fnmatch(process, pattern):
                continue

            title_contains = rule.get("title_contains")
            if title_contains:
                values = title_contains if isinstance(title_contains, list) else [title_contains]
                if not any(str(value).lower() in title for value in values):
                    continue

            score = self._specificity_score(pattern, title_contains)
            if score > best_score:
                best_score = score
                best_rule = rule

        if not best_rule:
            return [self.default_tag]

        tag = best_rule.get("tag") or self.default_tag
        if isinstance(tag, list):
            tags = [str(item) for item in tag if item]
        else:
            tags = [str(tag)]
        return tags or [self.default_tag]

    def known_tags(self) -> set[str]:
        tags = {self.default_tag, "away"}
        for rule in self.rules:
            raw_tag = rule.get("tag") or self.default_tag
            if isinstance(raw_tag, list):
                tags.update(str(item) for item in raw_tag if item)
            elif raw_tag:
                tags.add(str(raw_tag))
        return tags

    @staticmethod
    def _specificity_score(pattern: str, title_contains: Any) -> int:
        wildcard_count = pattern.count("*") + pattern.count("?")
        score = max(0, len(pattern) - wildcard_count * 4)
        if "*" not in pattern and "?" not in pattern:
            score += 1000
        if title_contains:
            if isinstance(title_contains, list):
                score += max(len(str(item)) for item in title_contains)
            else:
                score += len(str(title_contains))
        return score


class ActivityStorage:
    def __init__(self, root: Path | None = None):
        self.root = root or default_data_root()
        self.root.mkdir(parents=True, exist_ok=True)

    def daily_jsonl_path(self, day: date) -> Path:
        return self.root / f"{day.isoformat()}.jsonl"

    def summary_path(self, day: date, redacted: bool = False) -> Path:
        suffix = "_summary_redacted.md" if redacted else "_summary.md"
        return self.root / f"{day.isoformat()}{suffix}"

    def append_segment(self, segment: dict[str, Any]) -> None:
        day = datetime.fromisoformat(segment["start_ts"]).date()
        path = self.daily_jsonl_path(day)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(segment, ensure_ascii=False, separators=(",", ":")) + "\n")

    def read_segments(self, day: date) -> list[dict[str, Any]]:
        path = self.daily_jsonl_path(day)
        if not path.exists():
            return []

        segments: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    segments.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSONL at {path}:{line_number}") from exc
        return segments


def append_exception_log(log_path: Path, exc: BaseException) -> None:
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{now_local().isoformat(timespec='seconds')}]\n")
            handle.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
            handle.write("\n")
    except Exception:
        pass


def get_active_window() -> WindowInfo:
    if os.name != "nt":
        raise RuntimeError("Window polling is only supported on Windows.")

    try:
        import win32api
        import win32con
        import win32gui
        import win32process
    except ImportError as exc:
        raise RuntimeError("Missing dependency pywin32. Run: pip install -r requirements.txt") from exc

    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return WindowInfo(title="", process_name="unknown", exe_path="")

    title = win32gui.GetWindowText(hwnd) or ""
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    exe_path = ""
    process_name = f"pid-{pid}" if pid else "unknown"

    handle = None
    try:
        access = win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ
        handle = win32api.OpenProcess(access, False, pid)
        exe_path = win32process.GetModuleFileNameEx(handle, 0)
        if exe_path:
            process_name = Path(exe_path).name
    except Exception:
        try:
            module = win32gui.GetWindowModuleFileName(hwnd)
            if module:
                exe_path = module
                process_name = Path(module).name
        except Exception:
            pass
    finally:
        if handle is not None:
            try:
                win32api.CloseHandle(handle)
            except Exception:
                pass

    if process_name.startswith("pid-"):
        try:
            import psutil
            proc = psutil.Process(pid)
            resolved = proc.name() or ""
            if resolved:
                process_name = resolved
                exe_path = proc.exe() or exe_path
        except Exception:
            pass

    return WindowInfo(title=title, process_name=process_name, exe_path=exe_path)


class ActivityTracker:
    def __init__(
        self,
        storage: ActivityStorage,
        rules: RuleEngine,
        poll_interval: float = 2.0,
        away_minutes: float = 5.0,
    ):
        self.storage = storage
        self.rules = rules
        self.poll_interval = max(0.5, float(poll_interval))
        self.away_threshold = timedelta(minutes=max(0.1, float(away_minutes)))
        self.keyboard_counter = PollingKeyboardTracker()
        self._stop_event = threading.Event()
        # v2: process-level tracking state
        self._tool_sessions: dict[str, set[int]] = {}
        self._tool_wall_ceiling: dict[str, float] = self._load_tool_wall(date.today())
        self._peak_concurrency = 0
        self._peak_concurrency_at: str | None = None

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        active_window = get_active_window()
        current = self._start_segment(active_window, now_local())
        last_seen_window_key = active_window.key()
        last_activity_ts = now_local()
        state_keyboard_snapshot = self.keyboard_counter.snapshot()
        state_sample_ts = now_local()
        last_state_write_ts: datetime | None = None
        state_keyboard_snapshot, state_sample_ts = self._write_current_state_safe(
            current,
            state_sample_ts,
            state_keyboard_snapshot,
            state_sample_ts,
        )
        last_state_write_ts = state_sample_ts

        try:
            while not self._stop_event.wait(self.poll_interval):
                now = now_local()
                self.keyboard_counter.poll()
                state_changed = False

                if current.start_ts.date() != now.date():
                    boundary = datetime.combine(now.date(), day_time.min)
                    self._finish_segment(current, boundary)
                    current = self._start_segment(current.window, boundary, is_away=current.is_away)
                    state_changed = True
                    # v2: reset tool tracking for new day
                    self._tool_sessions.clear()
                    self._peak_concurrency = 0
                    self._peak_concurrency_at = None

                active_window = get_active_window()
                active_key = active_window.key()
                window_changed = active_key != last_seen_window_key
                key_activity_ts = self.keyboard_counter.last_key_ts()
                key_activity = key_activity_ts > last_activity_ts

                if window_changed:
                    last_seen_window_key = active_key
                    last_activity_ts = now
                elif key_activity:
                    last_activity_ts = key_activity_ts

                if current.is_away:
                    if window_changed or key_activity:
                        self._finish_segment(current, now, keyboard_stats=empty_keyboard_stats())
                        current = self._start_segment(active_window, now)
                        state_changed = True
                    if state_changed or self._current_state_heartbeat_due(now, last_state_write_ts):
                        state_keyboard_snapshot, state_sample_ts = self._write_current_state_safe(
                            current,
                            now,
                            state_keyboard_snapshot,
                            state_sample_ts,
                        )
                        last_state_write_ts = state_sample_ts
                    continue

                if now - last_activity_ts >= self.away_threshold:
                    away_start = last_activity_ts + self.away_threshold
                    if away_start <= current.start_ts:
                        away_start = now
                    self._finish_segment(current, away_start)
                    current = self._start_segment(self._away_window(), away_start, is_away=True)
                    state_keyboard_snapshot, state_sample_ts = self._write_current_state_safe(
                        current,
                        now,
                        state_keyboard_snapshot,
                        state_sample_ts,
                    )
                    last_state_write_ts = state_sample_ts
                    continue

                if window_changed:
                    self._finish_segment(current, now)
                    current = self._start_segment(active_window, now)
                    state_changed = True

                if state_changed or self._current_state_heartbeat_due(now, last_state_write_ts):
                    state_keyboard_snapshot, state_sample_ts = self._write_current_state_safe(
                        current,
                        now,
                        state_keyboard_snapshot,
                        state_sample_ts,
                    )
                    last_state_write_ts = state_sample_ts
        finally:
            self._finish_segment(current, now_local())

    def _start_segment(self, window: WindowInfo, start_ts: datetime, is_away: bool = False) -> SegmentState:
        tags = ["away"] if is_away else self.rules.match(window)
        return SegmentState(
            segment_id=str(uuid.uuid4()),
            start_ts=start_ts,
            window=window,
            tags=tags,
            keyboard_snapshot=self.keyboard_counter.snapshot(),
            is_away=is_away,
        )

    def _finish_segment(
        self,
        segment: SegmentState,
        end_ts: datetime,
        keyboard_stats: dict[str, int] | None = None,
    ) -> None:
        if end_ts <= segment.start_ts:
            return

        if keyboard_stats is None:
            keyboard_stats = counter_to_keyboard_stats(self.keyboard_counter.diff_since(segment.keyboard_snapshot))

        duration_sec = int(round((end_ts - segment.start_ts).total_seconds()))
        if duration_sec <= 0:
            return

        payload = {
            "segment_id": segment.segment_id,
            "start_ts": segment.start_ts.isoformat(timespec="seconds"),
            "end_ts": end_ts.isoformat(timespec="seconds"),
            "duration_sec": duration_sec,
            "window": {
                "title": segment.window.title,
                "process_name": segment.window.process_name,
                "exe_path": segment.window.exe_path,
            },
            "keyboard": keyboard_stats,
            "tags": segment.tags,
        }
        self.storage.append_segment(payload)

    def _write_current_state_safe(
        self,
        current: SegmentState,
        now: datetime,
        previous_keyboard_snapshot: Counter[str],
        previous_sample_ts: datetime,
    ) -> tuple[Counter[str], datetime]:
        try:
            keyboard_diff = self.keyboard_counter.diff_since(previous_keyboard_snapshot)
            interval_seconds = max(0.0, (now - previous_sample_ts).total_seconds())
            idle_seconds = max(0, int((now - self.keyboard_counter.last_key_ts()).total_seconds()))
            # v2: sample tool processes (fail-soft)
            tool_processes = self._sample_tool_processes()
            snapshot = build_current_state_snapshot(
                now=now,
                current=current,
                idle_seconds=idle_seconds,
                today_segments=self.storage.read_segments(now.date()),
                keyboard_diff=keyboard_diff,
                recent_interval_seconds=interval_seconds,
                known_categories=self.rules.known_tags(),
                tool_processes=tool_processes,
                peak_concurrency=self._peak_concurrency,
                peak_concurrency_at=self._peak_concurrency_at,
            )
            write_current_state_atomic(self.storage.root, snapshot)
        except Exception as exc:
            append_exception_log(self.storage.root / "agent_error.log", exc)
        return self.keyboard_counter.snapshot(), now

    @staticmethod
    def _current_state_heartbeat_due(now: datetime, last_write_ts: datetime | None) -> bool:
        if last_write_ts is None:
            return True
        return (now - last_write_ts).total_seconds() >= CURRENT_STATE_HEARTBEAT_SECONDS

    @staticmethod
    def _away_window() -> WindowInfo:
        return WindowInfo(title="Away", process_name="away", exe_path="")

    # ── v2: process-level tracking ──

    def _tool_wall_path(self, day: date) -> Path:
        return self.storage.root / f"tool_wall_{day.isoformat()}.json"

    def _load_tool_wall(self, day: date) -> dict[str, float]:
        path = self._tool_wall_path(day)
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _persist_tool_wall(self) -> None:
        path = self._tool_wall_path(date.today())
        try:
            with path.open("w", encoding="utf-8") as f:
                json.dump(self._tool_wall_ceiling, f, ensure_ascii=False)
        except Exception:
            pass

    def _sample_tool_processes(self) -> list[dict[str, Any]]:
        """Sample running tool processes via psutil. Fail-soft: returns [] on any error."""
        try:
            import psutil  # type: ignore[import-untyped]
        except ImportError:
            return []

        now = now_local()
        today = now.date()

        # Group raw processes by exe name
        tool_groups: dict[str, list[Any]] = defaultdict(list)
        try:
            for proc in psutil.process_iter(["pid", "name", "create_time"]):
                try:
                    name: str = proc.info.get("name", "") or ""
                    if name not in TOOL_MAP:
                        continue
                    tool_groups[name].append(proc)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass

        # Collect window titles by PID
        pid_titles: dict[int, str] = {}
        try:
            import win32gui
            import win32process

            def _enum_cb(hwnd: int, _ctx: Any) -> bool:
                if not win32gui.IsWindowVisible(hwnd):
                    return True
                try:
                    _, wpid = win32process.GetWindowThreadProcessId(hwnd)
                    if wpid and wpid not in pid_titles:
                        t = win32gui.GetWindowText(hwnd)
                        if t:
                            pid_titles[wpid] = t
                except Exception:
                    pass
                return True

            win32gui.EnumWindows(_enum_cb, None)
        except Exception:
            pass

        # Aggregate by tool_id
        agg: dict[str, dict[str, Any]] = {}
        for exe_name, procs in tool_groups.items():
            tool_info = TOOL_MAP[exe_name]
            tool_id = tool_info["id"]

            if tool_id not in agg:
                agg[tool_id] = {
                    "label": tool_info["label"],
                    "exe": exe_name,
                    "earliest_start": None,
                    "total_cpu_minutes": 0.0,
                    "pids": list[int](),
                    "titles": list[str](),
                }

            entry = agg[tool_id]
            for proc in procs:
                try:
                    pid: int = proc.pid
                    create_ts = proc.info.get("create_time")
                    if not create_ts:
                        continue
                    started_at = datetime.fromtimestamp(create_ts)

                    if entry["earliest_start"] is None or started_at < entry["earliest_start"]:
                        entry["earliest_start"] = started_at
                    entry["pids"].append(pid)

                    try:
                        cpu = proc.cpu_times()
                        entry["total_cpu_minutes"] += (cpu.user + cpu.system) / 60.0
                    except Exception:
                        pass

                    title = pid_titles.get(pid, "")
                    if title:
                        entry["titles"].append(title)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

        # Build output list
        results: list[dict[str, Any]] = []

        for tool_id, entry in agg.items():
            if not entry["pids"] or entry["earliest_start"] is None:
                continue

            # Track unique PIDs for session count
            if tool_id not in self._tool_sessions:
                self._tool_sessions[tool_id] = set()
            for pid in entry["pids"]:
                self._tool_sessions[tool_id].add(pid)
            session_count = len(self._tool_sessions[tool_id])

            # Wall time — today portion only
            est: datetime = entry["earliest_start"]
            if est.date() == today:
                wall_seconds = (now - est).total_seconds()
            elif est < datetime.combine(today, day_time.min):
                wall_seconds = (now - datetime.combine(today, day_time.min)).total_seconds()
            else:
                wall_seconds = max(0.0, (now - est).total_seconds())

            wall_minutes = round(wall_seconds / 60.0, 1)
            cpu_minutes = round(entry["total_cpu_minutes"], 2)

            # Persist wall ceiling: even if this process dies later, its contribution is preserved
            merged_wall = max(wall_minutes, self._tool_wall_ceiling.get(tool_id, 0.0))
            self._tool_wall_ceiling[tool_id] = merged_wall

            # Best title + task hint
            best_title = ""
            task_hint: str | None = None
            for title in entry["titles"]:
                hint = extract_task_hint(title)
                if hint:
                    task_hint = hint
                    if not best_title:
                        best_title = title
                elif not best_title:
                    best_title = title

            last_title = sanitize_title(best_title) if best_title else entry["exe"]

            # Use persisted ceiling as wall (preserves dead-process contributions)
            display_wall = self._tool_wall_ceiling.get(tool_id, wall_minutes)

            results.append({
                "id": tool_id,
                "label": entry["label"],
                "exe": entry["exe"],
                "pid": entry["pids"][0],
                "started_at": entry["earliest_start"].isoformat(timespec="seconds"),
                "wall_minutes": display_wall,
                "cpu_minutes": cpu_minutes,
                "session_count": session_count,
                "last_title": last_title,
                "task_hint": task_hint,
            })

        # Persist wall ceiling after every sample
        self._persist_tool_wall()

        # Update concurrency peak
        active_count = len(results)
        if active_count > self._peak_concurrency:
            self._peak_concurrency = active_count
            self._peak_concurrency_at = now.isoformat(timespec="seconds")

        return results


def format_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def bar(value: float, max_value: float, width: int = 18) -> str:
    if max_value <= 0 or value <= 0:
        return ""
    filled = max(1, int(round((value / max_value) * width)))
    return "#" * min(width, filled)


def segment_tag(segment: dict[str, Any]) -> str:
    tags = segment.get("tags") or ["other"]
    return str(tags[0] if tags else "other")


def segment_state_tag(segment: SegmentState) -> str:
    if segment.is_away:
        return "away"
    return str(segment.tags[0] if segment.tags else "other")


def ordered_category_seconds(
    seconds_by_category: dict[str, int],
    known_categories: Iterable[str] | None = None,
) -> dict[str, int]:
    categories = set(known_categories or [])
    categories.update(seconds_by_category)
    ordered = [category for category in CURRENT_STATE_CATEGORY_ORDER if category in categories]
    ordered.extend(sorted(category for category in categories if category not in ordered))
    return {category: int(seconds_by_category.get(category, 0)) for category in ordered}


def build_current_state_snapshot(
    *,
    now: datetime,
    current: SegmentState,
    idle_seconds: int,
    today_segments: list[dict[str, Any]],
    keyboard_diff: Counter[str] | dict[str, int],
    recent_interval_seconds: float,
    known_categories: Iterable[str] | None = None,
    tool_processes: list[dict[str, Any]] | None = None,
    peak_concurrency: int = 0,
    peak_concurrency_at: str | None = None,
) -> dict[str, Any]:
    today = now.date()
    seconds_by_category: defaultdict[str, float] = defaultdict(float)

    for segment in today_segments:
        duration = float(segment.get("duration_sec") or 0)
        if duration <= 0:
            continue
        seconds_by_category[segment_tag(segment)] += duration

    current_start = max(current.start_ts, datetime.combine(today, day_time.min))
    if current_start.date() == today and now > current_start:
        seconds_by_category[segment_state_tag(current)] += (now - current_start).total_seconds()

    rounded_seconds = {
        category: int(round(seconds))
        for category, seconds in seconds_by_category.items()
        if seconds > 0
    }
    category_seconds = ordered_category_seconds(rounded_seconds, known_categories)
    active_seconds = sum(seconds for category, seconds in category_seconds.items() if category != "away")
    total_keys = int(keyboard_diff.get("total_keys") or 0)
    if recent_interval_seconds > 0 and total_keys > 0:
        recent_keys_per_min = round(total_keys / (recent_interval_seconds / 60.0), 1)
    else:
        recent_keys_per_min = 0.0

    # ── v2: process-level fields ──
    away_seconds_today = seconds_by_category.get("away", 0.0)

    # Compute active ratio for effective wall time (avoid all-or-nothing away subtraction)
    total_tracked = active_seconds + away_seconds_today
    active_ratio = (active_seconds / total_tracked) if total_tracked > 0 else 1.0

    # Add effective_wall_minutes to each process entry
    processes: list[dict[str, Any]] = []
    if tool_processes:
        for p in tool_processes:
            enriched = dict(p)
            enriched["effective_wall_minutes"] = round(
                float(p.get("wall_minutes", 0)) * active_ratio, 1
            )
            processes.append(enriched)

    # Compute by_tool_minutes
    by_tool_minutes: dict[str, dict[str, float]] = {}
    for tool_id in TOOL_IDS:
        by_tool_minutes[tool_id] = {"wall": 0.0, "cpu": 0.0, "effective": 0.0}

    for p in processes:
        tid = str(p.get("id", ""))
        if tid in by_tool_minutes:
            w = float(p.get("wall_minutes", 0))
            c = float(p.get("cpu_minutes", 0))
            e = float(p.get("effective_wall_minutes", 0))
            by_tool_minutes[tid]["wall"] = max(by_tool_minutes[tid]["wall"], w)
            by_tool_minutes[tid]["cpu"] = round(by_tool_minutes[tid]["cpu"] + c, 2)
            by_tool_minutes[tid]["effective"] = max(by_tool_minutes[tid]["effective"], e)

    # Round by_tool_minutes values
    for tid in by_tool_minutes:
        for k in ("wall", "cpu", "effective"):
            by_tool_minutes[tid][k] = round(by_tool_minutes[tid][k], 1)

    concurrency_peaks = {
        "max_concurrent_tools": peak_concurrency,
        "at": peak_concurrency_at,
    }

    return {
        "schema_version": CURRENT_STATE_SCHEMA_VERSION,
        "updated_at": now.isoformat(timespec="seconds"),
        "current": {
            "category": segment_state_tag(current),
            "is_away": bool(current.is_away),
            "idle_seconds": max(0, int(idle_seconds)),
            "recent_keys_per_min": recent_keys_per_min,
        },
        "today": {
            "date": today.isoformat(),
            "active_seconds": int(active_seconds),
            "by_category_seconds": category_seconds,
            "by_tool_minutes": by_tool_minutes,
            "concurrency_peaks": concurrency_peaks,
        },
        "processes": processes,
    }


def write_current_state_atomic(root: Path, snapshot: dict[str, Any]) -> None:
    tmp_path = root / "current_state.json.tmp"
    final_path = root / "current_state.json"
    root.mkdir(parents=True, exist_ok=True)
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp_path, final_path)


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def merge_timeline(segments: list[dict[str, Any]], redacted: bool = False) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for segment in sorted(segments, key=lambda item: item.get("start_ts", "")):
        tag = segment_tag(segment)
        start_ts = parse_ts(segment["start_ts"])
        end_ts = parse_ts(segment["end_ts"])
        duration = float(segment.get("duration_sec") or (end_ts - start_ts).total_seconds())
        process = f"{tag}-app" if redacted else (segment.get("window") or {}).get("process_name") or "unknown"

        if merged and merged[-1]["tag"] == tag and start_ts <= merged[-1]["end_ts"] + timedelta(seconds=3):
            merged[-1]["end_ts"] = end_ts
            merged[-1]["duration_sec"] += duration
            merged[-1]["processes"].add(process)
        else:
            merged.append(
                {
                    "tag": tag,
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                    "duration_sec": duration,
                    "processes": {process},
                }
            )
    return merged


def generate_summary(day: date, storage: ActivityStorage, redacted: bool = False) -> str:
    segments = storage.read_segments(day)
    weekday = "一二三四五六日"[day.weekday()]
    lines: list[str] = [f"# {day.month}月{day.day}日（{weekday}）活动时间线", ""]
    if redacted:
        lines.extend(["公开展示脱敏版：已隐藏真实应用名、窗口标题、可执行路径和数据文件路径。", ""])

    if not segments:
        lines.extend(
            [
                "未发现当天活动记录。",
                "",
            ]
        )
        if not redacted:
            lines.append(f"数据文件：{storage.daily_jsonl_path(day)}")
        markdown = "\n".join(lines)
        storage.summary_path(day, redacted=redacted).write_text(markdown, encoding="utf-8")
        return markdown

    tag_seconds: defaultdict[str, float] = defaultdict(float)
    process_seconds: defaultdict[str, float] = defaultdict(float)
    keyboard_totals: Counter[str] = Counter()
    coding_keys = 0
    coding_delete_keys = 0
    coding_seconds = 0.0
    coding_peak_kpm = 0.0

    for segment in segments:
        duration = float(segment.get("duration_sec") or 0)
        tag = segment_tag(segment)
        keyboard = segment.get("keyboard") or {}
        process = f"{tag}-app" if redacted else (segment.get("window") or {}).get("process_name") or "unknown"

        tag_seconds[tag] += duration
        process_seconds[process] += duration
        keyboard_totals.update({key: int(keyboard.get(key) or 0) for key in empty_keyboard_stats()})

        if tag == "coding":
            total_keys = int(keyboard.get("total_keys") or 0)
            delete_keys = int(keyboard.get("delete_keys") or 0)
            coding_keys += total_keys
            coding_delete_keys += delete_keys
            coding_seconds += duration
            if duration > 0:
                coding_peak_kpm = max(coding_peak_kpm, total_keys / (duration / 60.0))

    max_tag_seconds = max(tag_seconds.values()) if tag_seconds else 0
    preferred_order = ["coding", "browsing", "gaming", "chat", "away", "other"]
    ordered_tags = preferred_order + sorted(tag for tag in tag_seconds if tag not in preferred_order)

    for tag in ordered_tags:
        seconds = tag_seconds.get(tag, 0)
        if seconds <= 0 and tag not in {"gaming"}:
            continue
        suffix = "(未检测到)" if seconds <= 0 else bar(seconds, max_tag_seconds)
        lines.append(f"- {tag:<8} {format_duration(seconds):>9}  {suffix}")

    active_seconds = sum(seconds for tag, seconds in tag_seconds.items() if tag != "away")
    lines.extend(["", f"活跃总计：{format_duration(active_seconds)}", ""])

    avg_coding_kpm = coding_keys / (coding_seconds / 60.0) if coding_seconds > 0 else 0.0
    delete_rate = (coding_delete_keys / coding_keys * 100.0) if coding_keys > 0 else 0.0

    # ── 趣味指标 ──
    total_keys = keyboard_totals['total_keys']
    wasd_ratio = (keyboard_totals['wasd_keys'] / total_keys * 100) if total_keys > 0 else 0
    direction_ratio = (keyboard_totals['direction_keys'] / total_keys * 100) if total_keys > 0 else 0
    shortcut_ratio = (keyboard_totals['modifier_keys'] / total_keys * 100) if total_keys > 0 else 0
    gaming_seconds = tag_seconds.get('gaming', 0)

    # 键速等级
    if coding_peak_kpm >= 80:
        speed_rank = '🏎️ F1 级 — 手速惊人，键盘在冒烟'
    elif coding_peak_kpm >= 60:
        speed_rank = '⚡ 职业级 — 闪电般的手指'
    elif coding_peak_kpm >= 40:
        speed_rank = '🎮 熟练玩家 — 已经很快了'
    elif coding_peak_kpm >= 20:
        speed_rank = '🚲 休闲节奏 — 稳扎稳打'
    else:
        speed_rank = '🦥 树懒模式 — 今天在摸鱼？'

    # WASD 竞技指数
    if gaming_seconds > 600:  # 打了超过 10 分钟游戏
        if wasd_ratio > 40:
            gaming_badge = '🎯 竞技射手 — WASD 根本没停过'
        elif wasd_ratio > 20:
            gaming_badge = '🎮 轻度玩家 — 偶尔来几局'
        else:
            gaming_badge = '🕹️ 非典型玩家 — 可能玩的是策略游戏'
    else:
        if wasd_ratio > 30:
            gaming_badge = '👀 没打游戏但 WASD 很高？你在编辑器里跑酷吗？'
        elif wasd_ratio > 10:
            gaming_badge = '⌨️ 轻度 WASD 使用者'
        else:
            gaming_badge = '🧘 WASD 几乎为 0，心如止水'

    # 热键将军
    if shortcut_ratio > 15:
        shortcut_badge = '🏅 热键将军 — 鼠标是摆设'
    elif shortcut_ratio > 8:
        shortcut_badge = '⌨️ 快捷键熟练工'
    else:
        shortcut_badge = '🖱️ 鼠标派 — 右键菜单才是真'

    # 编辑密集度（删除率评价）
    if delete_rate > 15:
        edit_badge = '✏️ 精雕细琢 — 删了写写了删，完美主义'
    elif delete_rate > 8:
        edit_badge = '📝 正常编辑节奏'
    elif delete_rate > 3 and coding_keys > 100:
        edit_badge = '🚀 一气呵成 — 删得少写得快'
    else:
        edit_badge = '📖 阅读为主 — 键盘更多在导航'

    lines.extend([
        "",
        "## 键盘活动",
        f"- 总击键：{total_keys:,} 次",
        f"- 编码场景键速：平均 {avg_coding_kpm:.0f} 键/分钟，峰值 {coding_peak_kpm:.0f} 键/分钟",
        f"- 编码场景删除率：{delete_rate:.1f}%",
        (
            "- 分类统计："
            f"字母 {keyboard_totals['letters']:,}，"
            f"数字 {keyboard_totals['numbers']:,}，"
            f"功能键 {keyboard_totals['function_keys']:,}，"
            f"方向键 {keyboard_totals['direction_keys']:,}，"
            f"修饰键 {keyboard_totals['modifier_keys']:,}，"
            f"WASD {keyboard_totals['wasd_keys']:,}，"
            f"删除键 {keyboard_totals['delete_keys']:,}"
        ),
        "",
        f"### 🏆 速度等级: {speed_rank}",
        f"### 🎮 WASD 竞技: {gaming_badge}",
        f"### ⌨️ 操作风格: {shortcut_badge} ｜ {edit_badge}",
    ])

    # 最长的连续活跃段
    longest_active = 0
    longest_start = ""
    for item in merge_timeline(segments, redacted=redacted):
        if item['tag'] != 'away':
            d = item['duration_sec']
            if d > longest_active:
                longest_active = d
                longest_start = item['start_ts'].strftime('%H:%M')
    if longest_active > 0:
        lines.append(f"### ⏱️ 最长专注: {format_duration(longest_active)}（自 {longest_start} 起）")

    # ── 每日称号 ──
    active_wo_away = {t: s for t, s in tag_seconds.items() if t != 'away'}
    if active_wo_away:
        dominant_tag = max(active_wo_away, key=active_wo_away.get)
        dominant_pct = active_wo_away[dominant_tag] / max(1, sum(active_wo_away.values())) * 100
    else:
        dominant_tag = 'away'
        dominant_pct = 100

    title_map = {
        'coding': ('💻 代码炼金术士', '今天你就是敲代码的神'),
        'gaming': ('🎮 电竞复活者', '游戏时间到！记得喝水'),
        'chat': ('💬 社交恐怖分子', '对话框里度过了一整天'),
        'browsing': ('🌊 网络冲浪选手', '信息海啸中穿梭自如'),
        'away': ('🛌 今天休息日', '身体是革命的本钱'),
    }
    title, motto = title_map.get(dominant_tag, ('🧑‍💻 全能生物', '什么都做了点，挺好'))
    if dominant_tag == 'coding' and dominant_pct > 80:
        title = '🔥 代码狂魔'
        motto = '你今天的产出够团队忙一星期'
    elif dominant_tag == 'coding' and coding_keys > 8000:
        title = '⚡ 闪电键盘手'
        motto = '键盘在你手下已经不是键盘了'

    lines.extend(["", f"# 🏅 今日称号：{title}", f"> {motto}", ""])

    # ── 活动热力图 ──
    hour_seconds = [0.0] * 24
    for segment in segments:
        start = parse_ts(segment['start_ts'])
        end = parse_ts(segment['end_ts'])
        dur = float(segment.get('duration_sec') or 0)
        tag = segment_tag(segment)
        if tag != 'away' and dur > 0:
            h = start.hour
            hour_seconds[h] += dur

    max_hour = max(hour_seconds) if max(hour_seconds) > 0 else 1
    heatmap_emoji = []
    for h in range(24):
        ratio = hour_seconds[h] / max_hour
        if ratio > 0.75:
            em = '🟩'
        elif ratio > 0.4:
            em = '🟨'
        elif ratio > 0.1:
            em = '🟦'
        elif hour_seconds[h] > 0:
            em = '⬜'
        else:
            em = '⬛'
        heatmap_emoji.append(em)

    # 检测夜间活动
    night_hours = sum(hour_seconds[h] for h in range(0, 6))  # 0:00-6:00
    late_hours = sum(hour_seconds[h] for h in range(22, 24))  # 22:00-24:00
    late_night_haver = [h for h in [*range(0, 6), *range(22, 24)] if hour_seconds[h] > 300]

    lines.append("## ⏰ 活动热力图（24小时）")
    hour_labels = ''.join(f'{h:2d}' if h % 2 == 0 else '  ' for h in range(24))
    lines.append(f"   {hour_labels}")
    lines.append(f"   {''.join(heatmap_emoji)}")

    if late_night_haver:
        hour_list = ', '.join(f'{h:02d}:00' for h in sorted(late_night_haver))
        lines.append(f"### 🦉 夜猫子警报：{hour_list} 还在活动！")
    elif night_hours > 0:
        lines.append(f"### 🌅 早鸟出没：凌晨 {night_hours/60:.0f} 分钟活跃")
    else:
        lines.append("### ☀️ 正常作息，今天太阳对劲")
    lines.append("")

    # ── 成就徽章 ──
    badges = []
    # 基础数据
    coding_hours = tag_seconds.get('coding', 0) / 3600
    chat_hours = tag_seconds.get('chat', 0) / 3600
    gaming_flag = tag_seconds.get('gaming', 0) > 60

    if total_keys >= 10000:
        badges.append('🎖️ 键盘勇者 — 日击键破万')
    elif total_keys >= 5000:
        badges.append('🎖️ 键盘心法 — 日击键过五千')
    if longest_active >= 7200:
        badges.append('🎖️ 马拉松选手 — 连续专注 2 小时+')
    elif longest_active >= 3600:
        badges.append('🎖️ 半马选手 — 连续专注 1 小时+')
    if coding_hours >= 8:
        badges.append('🎖️ 编码铁人 — 编码时长超 8 小时')
    elif coding_hours >= 4:
        badges.append('🎖️ 码畜光荣 — 编码 4 小时+')
    if not gaming_flag and coding_hours > 1:
        badges.append('🎖️ 零游戏自律日 🧘')
    if chat_hours >= 2:
        badges.append('🎖️ 社交恐怖分子 — 聊天 2 小时+')
    if delete_rate < 3 and coding_hours > 1:
        badges.append('🎖️ 键盘洁癖 — 删除率低于 3%')
    if coding_peak_kpm >= 80:
        badges.append('🎖️ 手速达人 — 峰值键速 80+')
    if coding_keys > 0 and total_keys > 0:
        typo_ratio = keyboard_totals.get('delete_keys', 0) / max(1, coding_keys) * 100
        if typo_ratio < 3 and coding_keys > 500:
            badges.append('🎖️ 指法入神 — 打错率<3%，键盘掌控力拉满')
    if late_night_haver:
        badges.append('🎖️ 夜行生物 — 凌晨还在战斗 🌙')
    if active_seconds >= 14400:  # 4h
        badges.append('🎖️ 今天很充实 — 活跃 4 小时+')

    if badges:
        lines.append("## 🏆 今日成就")
        for b in badges:
            lines.append(f"- {b}")
        lines.append("")

    lines.append("")
    lines.append("## 应用 TOP5")

    for index, (process, seconds) in enumerate(
        sorted(process_seconds.items(), key=lambda item: item[1], reverse=True)[:5],
        1,
    ):
        lines.append(f"{index}. {process:<24} {format_duration(seconds)}")

    # ── 浏览器访问明细 ──
    if not redacted and tag_seconds.get('browsing', 0) > 60:
        domain_breakdown = browser_history.analyze_browser(segments)
        if domain_breakdown:
            sorted_domains = sorted(domain_breakdown.items(), key=lambda kv: kv[1], reverse=True)
            lines.extend(["", "## 🌐 浏览明细"])
            for domain, dur in sorted_domains[:10]:
                lines.append(f"- {domain:<40} {format_duration(dur)}")
            other_dur = sum(d for _, d in sorted_domains[10:])
            if other_dur > 0:
                lines.append(f"- {'其他':<40} {format_duration(other_dur)}")

    lines.extend(["", "## 归并时间线"])
    for item in merge_timeline(segments, redacted=redacted):
        start_label = item["start_ts"].strftime("%H:%M")
        end_label = item["end_ts"].strftime("%H:%M")
        process_label = ", ".join(sorted(item["processes"])[:3])
        if len(item["processes"]) > 3:
            process_label += ", ..."
        lines.append(
            f"- {start_label}-{end_label}  {item['tag']}  {format_duration(item['duration_sec'])}  {process_label}"
        )

    markdown = "\n".join(lines)
    storage.summary_path(day, redacted=redacted).write_text(markdown, encoding="utf-8")
    return markdown


def install_startup_task(script_path: Path) -> str:
    python_exe = Path(sys.executable)
    pythonw = python_exe.with_name("pythonw.exe")
    runner = pythonw if pythonw.exists() else python_exe
    task_command = f'"{runner}" "{script_path}"'
    command = [
        "schtasks",
        "/Create",
        "/TN",
        TASK_NAME,
        "/SC",
        "ONLOGON",
        "/TR",
        task_command,
        "/F",
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"Task Scheduler registration failed: {stderr}")
    return f"Registered {TASK_NAME}: {task_command}"


def log_unhandled_exception(exc: BaseException) -> None:
    try:
        storage = ActivityStorage()
        append_exception_log(storage.root / "agent_error.log", exc)
    except Exception:
        pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local activity tracker MVP")
    parser.add_argument("--install", action="store_true", help="Register a Windows logon startup task")
    parser.add_argument("--summary", nargs="?", const="", help="Write and print a daily summary, optional YYYY-MM-DD")
    parser.add_argument(
        "--summary-redacted",
        nargs="?",
        const="",
        help="Write and print a redacted daily summary for public screenshots, optional YYYY-MM-DD",
    )
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES_PATH, help="Path to rules.yaml")
    parser.add_argument("--data-root", type=Path, default=None, help="Override activity data root")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Foreground window poll interval in seconds")
    parser.add_argument("--away-minutes", type=float, default=5.0, help="Minutes with no key/window activity before away")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    storage = ActivityStorage(args.data_root)

    if args.install:
        print(install_startup_task(Path(__file__).resolve()))
        return 0

    if args.summary is not None or args.summary_redacted is not None:
        if args.summary is not None and args.summary_redacted is not None:
            raise RuntimeError("Use only one of --summary or --summary-redacted.")
        summary_arg = args.summary if args.summary is not None else args.summary_redacted
        summary_day = parse_date(summary_arg or None)
        print(generate_summary(summary_day, storage, redacted=args.summary_redacted is not None))
        return 0

    rules = RuleEngine(args.rules)
    tracker = ActivityTracker(
        storage=storage,
        rules=rules,
        poll_interval=args.poll_interval,
        away_minutes=args.away_minutes,
    )
    try:
        tracker.run()
    except KeyboardInterrupt:
        tracker.stop()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BaseException as exc:
        if not isinstance(exc, SystemExit):
            log_unhandled_exception(exc)
        raise
