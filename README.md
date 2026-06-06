# DayMate

DayMate is a tiny Windows-first daily companion tracker. It records foreground
window segments, keyboard activity counts, rule-based tags, JSONL history, and
playful Markdown daily summaries.

## Features

- Local-only storage by default
- Foreground window polling
- Keyboard count aggregation without storing typed text
- Rule-based tagging through `rules.yaml`
- JSONL activity records
- Markdown daily summaries with playful badges and milestones
- Redacted summary mode for public screenshots

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```powershell
python daymate.py --rules rules.yaml
```

Generate a daily summary:

```powershell
python daymate.py --summary 2026-01-01
```

Generate a redacted summary for public screenshots:

```powershell
python daymate.py --summary-redacted 2026-01-01
```

Use a custom data directory:

```powershell
python daymate.py --data-root "$env:USERPROFILE\.daymate\data"
```

## Sanitize Before Publishing

Run the public-tree leak check:

```powershell
python scripts/sanitize_check.py .
```

After creating a Git repository for the public copy, install the pre-push hook:

```powershell
python scripts/install_pre_push_hook.py .
```

## Privacy Notes

The tracker stores active window titles, process names, coarse keyboard counts,
and timestamps. It does not store typed text. Review your generated JSONL and
summary files before publishing examples or screenshots, and prefer
`--summary-redacted` for public visuals.

## License

MIT
