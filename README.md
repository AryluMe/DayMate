# DayMate

**DayMate** — a tiny Windows companion that watches your back, counts your keys, and gives you silly titles at the end of the day. 🫂

No cloud. No login. No "we care about your privacy" speech — it literally lives on your machine and talks to no one.

## Features

### 🏅 Daily Title
Every evening it looks at what you actually did and picks a title for you:

> 🔥 Title: Code Alchemist
> — Your output today could keep a team busy for a week.

Or maybe you'll get **🦥 Sloth Mode**, **💬 Social Butterfly**, **🎮 E-sports Reborn**, **☀️ Early Bird**... depends on your day.

### 🏆 Achievement Badges
Collectible badges that unlock automatically:

| Badge | Unlock Condition |
|-------|-----------------|
| 🎖️ Keyboard Warrior | 10,000+ keystrokes in a day |
| 🎖️ Marathon Runner | 2h+ continuous focus |
| 🎖️ Code Ironman | 8h+ coding |
| 🎖️ No-Game Day | Self-discipline mode |
| 🎖️ Nightwalker | Active after midnight |
| 🎖️ Keyboard Perfectionist | Delete rate < 3% |
| 🎖️ Speed Demon | Peak 80+ KPM |
| 🎖️ Marathon Runner | 2h+ continuous focus |

...and more you'll discover.

### ⏰ 24h Activity Heatmap
See your productive peaks at a glance:

```
    0   4   8   12  16  20
   ⬛⬛⬛⬛🟩🟨🟩🟩🟩🟩🟩🟩🟨⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛
```

Auto-detects whether you're a night owl or an early bird. 🦉🌅

### ⌨️ Keyboard Stats
- **WASD density** — gaming detection
- **KPM** (keystrokes per minute) — typing speed ranking
- **Delete rate** — are you a perfectionist or a speed typer?
- **Modifier key ratio** — hotkey master or mouse person?

### 🎮 Activity Timeline
```
- coding        3h 42m  ##################
- chat          1h 15m  ######
- gaming        0m      (not detected)
- away          2h 30m  ############
```

## Quick Start

```powershell
# Install
pip install -r requirements.txt

# Run (it sits in your system tray silently)
python daymate.py

# See today's summary
python daymate.py --summary today

# Redacted summary (safe for screenshots)
python daymate.py --summary-redacted today
```

## Custom Rules

Edit `rules.yaml` to teach DayMate what counts as "coding", "gaming", "browsing", etc. by process name and window title patterns.

```yaml
rules:
  - tag: coding
    process: editor.exe
  - tag: gaming
    process: game.exe
    window: "*"
```

## Privacy

- Everything runs **locally**. Zero network calls.
- Data stored in `~/.daymate/data/`
- Keystroke counts only — **no typed text is ever recorded**
- Use `--summary-redacted` for public screenshots that mask app names

## Why "DayMate"?

"Day" + "Mate" — a mate that walks through your day with you. Quiet, judgmental in a loving way, and always ready to give you a badge at the end.

## License

MIT
