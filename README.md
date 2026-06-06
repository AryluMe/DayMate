
<p align="center">
  <h1>DayMate 🫂</h1>
  <p align="center">A tiny Windows companion that watches your back,<br>counts your keys, and gives you silly titles at the end of the day.</p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/OS-Windows-blue?style=flat-square">
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square">
  <img src="https://img.shields.io/badge/status-whimsical-orange?style=flat-square">
  <img src="https://img.shields.io/badge/privacy-local_only-ff69b4?style=flat-square">
</p>

---

No cloud. No login. No "we care about your privacy" speech — it literally lives on **your machine** and talks to **no one**.

You won't even know it's there, until one evening it says:

> 🔥 **Today's Title: Code Alchemist**  
> *— Your output today could keep a team busy for a week.*

And you think: *huh. okay. that's actually kind of nice.*

## 🏅 What It Does

### It Gives You a Daily Title

Every evening DayMate looks at what you actually did all day and picks a fitting title:

| Title | When |
|-------|------|
| 🔥 Code Alchemist | You wrote a novel today |
| ⚡ Speed Demon | Peak typing speed > 80 KPM |
| 💬 Social Butterfly | You spent the whole day in chat apps |
| 🎮 E-sports Reborn | WASD was basically your keyboard today |
| 🦥 Sloth Mode | ...we all have those days |
| 🌅 Early Bird | Busy before most people wake up |
| 🦉 Nightwalker | Still going past midnight |

### It Collects Achievements for You

Play the long game. These unlock automatically:

| Badge | How |
|-------|-----|
| 🎖️ **Keyboard Warrior** | 10,000+ keystrokes in one day |
| 🎖️ **Marathon Runner** | 2h+ continuous focus without interruptions |
| 🎖️ **Code Ironman** | 8h+ coding in a single day |
| 🎖️ **No-Game Day** | A full day of self-discipline 🤝 |
| 🎖️ **Keyboard Perfectionist** | Delete rate < 3% — you don't make mistakes |
| 🎖️ **Nightwalker 🌙** | Active long after midnight |
| 🎖️ **Desktop Cleaner** | Average — you're a balanced human |

...and you'll discover more as you go.

### It Shows Your Day as a Heatmap

```
    0   4   8   12  16  20
   ⬛⬛⬛⬛🟩🟨🟩🟩🟩🟩🟩🟩🟨⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛
```

Green means "locked in." Gray means "probably eating." Black means "asleep like a normal person." It also tells you if you're more of a 🦉 night owl or a 🌅 early bird.

### It Knows Your Typing Habits

- **WASD density** — did you game today? it knows.
- **KPM** (keys per minute) — are you fast, or just mashing?
- **Delete rate** — are you a perfectionist or a "fix it later" kind of coder?
- **Hotkey ratio** — are you a keyboard wizard or a right-click peasant?

### Activity Timeline

```text
- coding         3h 42m  ##################
- chat           1h 15m  ######
- gaming         0m      (╯°□°）╯︵ ┻━┻  (none today)
- away           2h 30m  ############
```

## 🚀 Quick Start

```powershell
pip install -r requirements.txt
python daymate.py
```

That's it. It runs in the background, silently, like a small digital pet blinking at you from the corner of your desk.

Check your first summary:

```powershell
python daymate.py --summary today
```

Want to take a screenshot for social media?

```powershell
python daymate.py --summary-redacted today
```

It masks app names so you don't accidentally show the internet how much time you spend in ~~Discord~~ `chat-client.exe`.

## 🔧 Teach It Your Habits

Edit `rules.yaml` so DayMate learns what you do. Out of the box it understands common apps, but you can teach it anything:

```yaml
rules:
  - tag: coding
    process: editor.exe
  - tag: gaming
    process: game.exe
  - tag: reading
    process: pdf-reader.exe
```

## 🔒 Privacy

- Everything is **local**. Zero network calls. Ever.
- Stored in `~/.daymate/data/`
- **No keystroke text is ever saved** — just counts
- If you're paranoid, `--summary-redacted` is your friend

## 🤔 Why "DayMate"?

"Day" + "Mate". A companion that walks through your day with you.  
Quiet. Slightly judgmental in a loving way. Always ready with a badge at the end.

> *You don't need another productivity tool.*  
> *You just need someone to say "nice work" at the end of the day.*  
> That's DayMate.

## 📜 License

MIT — do whatever you want with it. Just keep the privacy notice intact.
