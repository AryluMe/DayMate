
<p align="center">
  <h1>DayMate 🫂</h1>
  <p align="center">一个小陪伴，看着你干活、数你敲了多少键、每天给你发一个称号。</p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/OS-Windows-blue?style=flat-square">
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square">
  <img src="https://img.shields.io/badge/status-whimsical-orange?style=flat-square">
  <img src="https://img.shields.io/badge/privacy-local_only-ff69b4?style=flat-square">
</p>

<p align="center">
  <b>中文 · <a href="#english">English</a></b>
</p>

---

不联网。不需要登录。没有什么「我们很重视您的隐私」的套话——它就老老实实待在你自己的电脑上，不和任何人说话。

你可能根本感觉不到它的存在，直到某天晚上它突然冒出一句：

> 🔥 **今日称号：代码炼金术士**
> ——你今天的产出够团队忙一星期。

你愣了一下。然后觉得……嗯，还挺有意思的。

---

## 🏅 它能做什么

### 每天给你发称号

DayMate 看你一整天都在干什么，挑一个合适的称号给你：

| 称号 | 什么情况 |
|------|---------|
| 🔥 代码炼金术士 | 你今天的代码量像写了一本小说 |
| ⚡ 闪电键盘手 | 峰值手速破 80 键/分钟 |
| 💬 社交恐怖分子 | 一整天都在对话框里度过 |
| 🎮 电竞复活者 | WASD 几乎占据了你今天的键盘 |
| 🦥 树懒模式 | 谁都有这么一天…… |
| 🌅 早鸟 | 大部分人还没醒你已经在干活了 |
| 🦉 夜行生物 | 凌晨还在战斗 |

### 解锁成就徽章

| 徽章 | 解锁条件 |
|------|---------|
| 🎖️ **键盘勇者** | 一天敲了一万次键盘 |
| 🎖️ **马拉松选手** | 连续专注 2 小时以上不中断 |
| 🎖️ **编码铁人** | 一天编码超 8 小时 |
| 🎖️ **零游戏自律日** | 整整一天没打开任何游戏 🤝 |
| 🎖️ **键盘洁癖** | 删除率不到 3%——你几乎不犯错 |
| 🎖️ **夜行生物 🌙** | 凌晨还在活跃 |
| 🎖️ **桌面清道夫** | 均衡发展，什么都做了一点 |

还有更多等你发掘。

### 24 小时热力图

```
    0   4   8   12  16  20
   ⬛⬛⬛⬛🟩🟨🟩🟩🟩🟩🟩🟩🟨⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛
```

绿色代表「心流」，灰色代表「大概在吃饭」，黑色代表「正常人类睡眠时间」。还会自动告诉你，你是 🦉 夜猫子体质还是 🌅 早鸟体质。

### 键盘行为分析

- **WASD 密度** —— 打没打游戏，它心里有数
- **键速 KPM** —— 你是真的快，还是在乱按？
- **删除率** —— 精雕细琢型选手，还是先写再说型？
- **快捷键比例** —— 键盘流高手，还是鼠标右键党？

### 活动时间线

```text
- 编码          3h 42m  ##################
- 聊天          1h 15m  ######
- 游戏          0m      (╯°□°）╯︵ ┻━┻（今天没打）
- 离开          2h 30m  ############
```

## 🚀 快速开始

```powershell
pip install -r requirements.txt
python daymate.py
```

就这样。它安安静静地在你后台跑着，像一个从桌角探出脑袋看你的小东西。

查看你的第一份日报：

```powershell
python daymate.py --summary today
```

想截个图发朋友圈？

```powershell
python daymate.py --summary-redacted today
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

```powershell
pip install -r requirements.txt
python daymate.py
```

```powershell
python daymate.py --summary today
python daymate.py --summary-redacted today  # safe for screenshots
```

## 🔒 Privacy

- **Local only.** Zero network calls.
- Data stored in `~/.daymate/data/`
- **No keystroke text is ever recorded** — just counts
- Use `--summary-redacted` for public screenshots that mask app names
- See [`docs/GITHUB_UPLOAD_FILTER.md`](docs/GITHUB_UPLOAD_FILTER.md) before pushing or sharing repository contents.

## License

MIT
