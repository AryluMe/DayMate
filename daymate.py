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
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time as day_time, timedelta
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_RULES_PATH = SCRIPT_DIR / "rules.yaml"
TASK_NAME = "DayMateActivityTracker"


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


class KeyboardCounter:
    def __init__(self, keyboard_mod: Any):
        self.keyboard = keyboard_mod
        self._lock = threading.Lock()
        self._counts: Counter[str] = Counter()
        self._last_key_ts = now_local()
        self._listener = None

        self.direction_keys = self._keys("up", "down", "left", "right")
        self.delete_keys = self._keys("backspace", "delete")
        self.modifier_keys = self._keys(
            "ctrl",
            "ctrl_l",
            "ctrl_r",
            "shift",
            "shift_l",
            "shift_r",
            "alt",
            "alt_l",
            "alt_r",
            "alt_gr",
            "cmd",
            "cmd_l",
            "cmd_r",
            "caps_lock",
        )
        self.function_keys = self._keys(*[f"f{i}" for i in range(1, 25)])

    def _keys(self, *names: str) -> set[Any]:
        keys = set()
        for name in names:
            value = getattr(self.keyboard.Key, name, None)
            if value is not None:
                keys.add(value)
        return keys

    def start(self) -> None:
        self._listener = self.keyboard.Listener(on_press=self.on_press)
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()

    def on_press(self, key: Any) -> None:
        updates: Counter[str] = Counter()
        updates["total_keys"] += 1

        char = getattr(key, "char", None)
        if char:
            if char.isalpha():
                updates["letters"] += 1
            elif char.isdigit():
                updates["numbers"] += 1
            if char.lower() in {"w", "a", "s", "d"}:
                updates["wasd_keys"] += 1
        else:
            if key in self.function_keys:
                updates["function_keys"] += 1
            if key in self.direction_keys:
                updates["direction_keys"] += 1
            if key in self.modifier_keys:
                updates["modifier_keys"] += 1
            if key in self.delete_keys:
                updates["delete_keys"] += 1

        with self._lock:
            self._counts.update(updates)
            self._last_key_ts = now_local()

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

    return WindowInfo(title=title, process_name=process_name, exe_path=exe_path)


class ActivityTracker:
    def __init__(
        self,
        storage: ActivityStorage,
        rules: RuleEngine,
        poll_interval: float = 2.0,
        away_minutes: float = 5.0,
    ):
        try:
            from pynput import keyboard
        except ImportError as exc:
            raise RuntimeError("Missing dependency pynput. Run: pip install -r requirements.txt") from exc

        self.storage = storage
        self.rules = rules
        self.poll_interval = max(0.5, float(poll_interval))
        self.away_threshold = timedelta(minutes=max(0.1, float(away_minutes)))
        self.keyboard_counter = KeyboardCounter(keyboard)
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        self.keyboard_counter.start()
        active_window = get_active_window()
        current = self._start_segment(active_window, now_local())
        last_seen_window_key = active_window.key()
        last_activity_ts = now_local()

        try:
            while not self._stop_event.wait(self.poll_interval):
                now = now_local()

                if current.start_ts.date() != now.date():
                    boundary = datetime.combine(now.date(), day_time.min)
                    self._finish_segment(current, boundary)
                    current = self._start_segment(current.window, boundary, is_away=current.is_away)

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
                    continue

                if now - last_activity_ts >= self.away_threshold:
                    away_start = last_activity_ts + self.away_threshold
                    if away_start <= current.start_ts:
                        away_start = now
                    self._finish_segment(current, away_start)
                    current = self._start_segment(self._away_window(), away_start, is_away=True)
                    continue

                if window_changed:
                    self._finish_segment(current, now)
                    current = self._start_segment(active_window, now)
        finally:
            self._finish_segment(current, now_local())
            self.keyboard_counter.stop()

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

    @staticmethod
    def _away_window() -> WindowInfo:
        return WindowInfo(title="Away", process_name="away", exe_path="")


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
        log_path = storage.root / "agent_error.log"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{now_local().isoformat(timespec='seconds')}]\n")
            handle.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
            handle.write("\n")
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
