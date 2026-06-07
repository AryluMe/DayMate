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

它会隐藏应用名，避免你不小心让全世界知道你在 ~~微信~~ 上花了多久。

## 🔧 教它认识你的习惯

编辑 `rules.yaml` 让 DayMate 认识你在干什么。内置规则已经覆盖常见应用，但你也可以自己定义：

```yaml
rules:
  - tag: coding
    process: editor.exe
  - tag: gaming
    process: game.exe
  - tag: reading
    process: pdf-reader.exe
```

## 🔒 隐私

- **纯本地运行。** 零网络请求。永远不联网。
- 数据存在 `~/.daymate/data/`
- **不记录任何键盘敲击的文本内容**，只统计次数
- 如果还是不放心，`--summary-redacted` 是你的好朋友
- 上传或分享仓库前，先看 [`docs/GITHUB_UPLOAD_FILTER.md`](docs/GITHUB_UPLOAD_FILTER.md)

## 🤔 为什么叫 DayMate？

"Day"（日常）+ "Mate"（伙伴）。一个陪你走过每一天的桌面伙伴。

安安静静的。带着一点爱的嫌弃。每天结束时，给你发一个徽章。

> *你不需要又一个生产力工具。*
> *你只是需要有人在一天结束的时候，跟你说一句「干得不错」。*
> 这就是 DayMate。

## 📜 开源许可

MIT ——随便你怎么用，保留隐私声明就行。

---

<h1 id="english"></h1>

<p align="center">
  <h1>DayMate 🫂</h1>
  <p align="center">A tiny Windows companion that watches your back,<br>counts your keys, and gives you silly titles at the end of the day.</p>
</p>

No cloud. No login. No "we care about your privacy" speech — it literally lives on **your machine** and talks to **no one**.

You won't even know it's there, until one evening it says:

> 🔥 **Today's Title: Code Alchemist**
> *— Your output today could keep a team busy for a week.*

And you think: *huh. okay. that's actually kind of nice.*

## 🏅 Features

### Daily Title

| Title | When |
|-------|------|
| 🔥 Code Alchemist | You wrote a novel today |
| ⚡ Speed Demon | 80+ KPM peak typing |
| 💬 Social Butterfly | Chat apps all day |
| 🎮 E-sports Reborn | WASD was your keyboard today |
| 🦥 Sloth Mode | ...we all have those days |
| 🌅 Early Bird | Active before most people wake up |
| 🦉 Nightwalker | Still going past midnight |

### Achievements

| Badge | How |
|-------|-----|
| 🎖️ **Keyboard Warrior** | 10,000+ keystrokes in one day |
| 🎖️ **Marathon Runner** | 2h+ continuous focus |
| 🎖️ **Code Ironman** | 8h+ coding in a single day |
| 🎖️ **No-Game Day** | A full day of self-discipline 🤝 |
| 🎖️ **Keyboard Perfectionist** | Delete rate < 3% |
| 🎖️ **Nightwalker 🌙** | Active past midnight |
| 🎖️ **Desktop Cleaner** | Balanced human |

### 24h Activity Heatmap

```
    0   4   8   12  16  20
   ⬛⬛⬛⬛🟩🟨🟩🟩🟩🟩🟩🟩🟨⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛
```

Green = locked in. Gray = probably eating. Black = sleeping. Night owl or early bird detection included.

### Keyboard Stats

- **WASD density** — did you game today?
- **KPM** (keys per minute) — speed demon or just mashing?
- **Delete rate** — perfectionist or "fix it later"?
- **Hotkey ratio** — keyboard wizard or right-click peasant?

## 🚀 Quick Start

Generate a redacted summary for public screenshots:

```powershell
python daymate.py --summary-redacted 2026-01-01
```

Use a custom data directory:

```powershell
python daymate.py --data-root "$env:USERPROFILE\.daymate\data"
```

## Sanitize Before Publishing

- **Local only.** Zero network calls.
- Data stored in `~/.daymate/data/`
- **No keystroke text is ever recorded** — just counts
- Use `--summary-redacted` for public screenshots that mask app names
- See [`docs/GITHUB_UPLOAD_FILTER.md`](docs/GITHUB_UPLOAD_FILTER.md) before pushing or sharing repository contents.

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
