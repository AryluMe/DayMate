from __future__ import annotations

import argparse
import stat
from pathlib import Path


HOOK_TEXT = """#!/bin/sh
python scripts/sanitize_check.py .
if [ $? -ne 0 ]; then
  echo "sanitize_check failed; push blocked." >&2
  exit 1
fi
"""


def install(repo_root: Path) -> Path:
    git_dir = repo_root / ".git"
    if not git_dir.is_dir():
        raise SystemExit(f"Not a git repository: {repo_root}")

    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / "pre-push"
    hook_path.write_text(HOOK_TEXT, encoding="utf-8")

    mode = hook_path.stat().st_mode
    hook_path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return hook_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install a pre-push sanitize_check hook for the public repo.")
    parser.add_argument("repo_root", nargs="?", default=".", type=Path, help="Public git repository root")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    hook_path = install(args.repo_root.resolve())
    print(f"Installed pre-push hook: {hook_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
