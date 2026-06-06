# GitHub Upload Filter

DayMate is safe to publish only when the repository contains source code,
documentation, and generic example rules. Runtime records are private by
default and must stay local.

## Do Not Upload

Never commit these files or folders:

- `~/.daymate/data/`
- `.daymate/`
- `data/`
- `*.jsonl`
- `*_summary*.md`
- `agent_error.log`
- `*.log`
- `.env` and `.env.*`
- private keys or certificates such as `*.pem`, `*.key`, `*.p12`, `*.pfx`
- local databases such as `*.db`, `*.sqlite`, `*.sqlite3`

Raw DayMate activity files can contain foreground window titles, process names,
executable paths, timestamps, and activity tags. Even when keystroke contents are
not recorded, those fields can still reveal private work, chat, browsing, or
game activity.

## Safe To Upload

These are expected public repository files:

- `daymate.py`
- `rules.yaml` with generic process names only
- `README.md`
- `requirements.txt`
- `LICENSE`
- `scripts/sanitize_check.py`
- `scripts/install_pre_push_hook.py`
- files under `docs/`

## Before Pushing

Run the repository sanitizer before pushing:

```powershell
python scripts/sanitize_check.py .
```

Optionally install the local pre-push hook:

```powershell
python scripts/install_pre_push_hook.py .
```

For screenshots or public sharing, generate a redacted summary:

```powershell
python daymate.py --summary-redacted today
```

Do not publish the raw JSONL files or the non-redacted `*_summary.md` output.
