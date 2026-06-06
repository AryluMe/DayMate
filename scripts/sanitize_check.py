from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path


TEXT_SUFFIXES = {
    ".cfg",
    ".gitignore",
    ".ini",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".txt",
    ".vbs",
    ".yaml",
    ".yml",
}

PRIVATE_PROCESS_NAME_PARTS = {
    ("Cur", "sor", ".exe"),
    ("Co", "dex", ".exe"),
    ("Windows", "Terminal", ".exe"),
    ("We", "Chat", ".exe"),
    ("Wei", "xin", ".exe"),
    ("Q", "Q", ".exe"),
    ("Lea", "gue", "*"),
    ("Gen", "shin", "*"),
    ("Star", "Rail", "*"),
}

BLOCKED_FILE_PATTERNS = [
    re.compile(r"(^|.*/)\.daymate/.*", re.IGNORECASE),
    re.compile(r"(^|.*/)data/.*", re.IGNORECASE),
    re.compile(r".*\.env(\..*)?$", re.IGNORECASE),
    re.compile(r".*\.pyc$", re.IGNORECASE),
    re.compile(r".*\.jsonl$", re.IGNORECASE),
    re.compile(r".*_summary.*\.md$", re.IGNORECASE),
    re.compile(r".*\.log$", re.IGNORECASE),
    re.compile(r".*\.(db|sqlite|sqlite3)$", re.IGNORECASE),
    re.compile(r".*\.(pem|key|p12|pfx)$", re.IGNORECASE),
    re.compile(r".*watchdog.*\.vbs$", re.IGNORECASE),
]

def private_process_names() -> set[str]:
    return {"".join(parts) for parts in PRIVATE_PROCESS_NAME_PARTS}


def secret_patterns() -> list[re.Pattern[str]]:
    return [
        re.compile(r"(?i)\b" + re.escape("D:" + "\\ai\\")),
        re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s]+"),
        re.compile(r"(?i)\b" + re.escape("C:" + "\\Users\\")),
        re.compile(r"(?i)\b" + re.escape("G:" + "\\")),
    ]


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int | None
    reason: str
    snippet: str = ""

    def render(self, root: Path) -> str:
        rel = self.path.relative_to(root)
        location = str(rel) if self.line is None else f"{rel}:{self.line}"
        if self.snippet:
            return f"{location} - {self.reason}: {self.snippet}"
        return f"{location} - {self.reason}"


def dynamic_secret_patterns() -> list[re.Pattern[str]]:
    patterns: list[re.Pattern[str]] = []
    username = os.environ.get("USERNAME")
    if username:
        patterns.append(re.compile(re.escape(username), re.IGNORECASE))
    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        patterns.append(re.compile(re.escape(userprofile), re.IGNORECASE))
    return patterns


def is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in {".gitignore", "LICENSE"}


def scan_path(root: Path, path: Path, patterns: list[re.Pattern[str]]) -> list[Finding]:
    findings: list[Finding] = []
    rel = path.relative_to(root).as_posix()

    for pattern in BLOCKED_FILE_PATTERNS:
        if pattern.fullmatch(rel):
            findings.append(Finding(path, None, "blocked generated/private file"))
            break

    if not is_text_file(path):
        return findings

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        findings.append(Finding(path, None, "non-UTF-8 text-like file"))
        return findings

    skip_process_name_policy_text = path.as_posix().endswith("scripts/sanitize_check.py")

    for index, line in enumerate(text.splitlines(), 1):
        for pattern in patterns:
            if pattern.search(line):
                findings.append(Finding(path, index, "private path or identifier", line.strip()[:180]))
        if not skip_process_name_policy_text:
            for process_name in private_process_names():
                if process_name in line:
                    findings.append(Finding(path, index, "private process name", line.strip()[:180]))

    return findings


def scan(root: Path) -> list[Finding]:
    if not root.exists():
        return [Finding(root, None, "path does not exist")]

    patterns = [*secret_patterns(), *dynamic_secret_patterns()]
    findings: list[Finding] = []
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if ".git" in path.parts:
            continue
        findings.extend(scan_path(root, path, patterns))
    return findings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fail if the public DayMate tree contains private data.")
    parser.add_argument("path", nargs="?", default="public", type=Path, help="Public tree to scan")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.path.resolve()
    findings = scan(root)
    if findings:
        print("sanitize_check failed:", file=sys.stderr)
        for finding in findings:
            print(f"  {finding.render(root)}", file=sys.stderr)
        return 1

    print(f"sanitize_check passed: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
