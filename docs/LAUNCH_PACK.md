# 发布启动包（Launch Pack）

> 用途：v4.2.0（及后续版本）对外发布的一站式执行包。
> 前置：`docs/RELEASE_CHECKLIST.md` 全部通过（先发版，后推广）。
> 本包包含：发布顺序 / 各渠道帖子**最终稿** / 发帖后 tracking 表 / 截图与录屏建议。
> 原则：真实、合规、可持续；每个渠道只发一次。

---

## 1. 发布顺序（Playbook）

| 步骤 | 动作 | 工具/位置 | 时机 |
|------|------|-----------|------|
| 1 | 打 tag `v4.x.y`（触发 release-simple.yml） | git push tag | 第 1 天上午 |
| 2 | 验证 Linux/Windows 资产 + Release notes | RELEASE_CHECKLIST §7 | 第 1 天（构建完成后） |
| 3 | GitHub topics / description SEO 设置 | 仓库 Settings | 第 1 天 |
| 4 | Show HN 发帖 | news.ycombinator.com | 第 1 天（建议 UTC 13:00–15:00，美东早间） |
| 5 | Reddit r/Python + r/selfhosted 发帖 | reddit.com | 第 2 天（错开 HN 高峰） |
| 6 | Awesome 列表投稿（3 个候选） | 各列表 PR/issue | 第 3–5 天 |
| 7 | 中文社区：掘金 + 知乎（可选 V2EX） | juejin.cn / zhihu.com | 第 4–7 天 |
| 8 | asciinema 录屏 + 替换 README「模拟」标注 | asciinema.org | 第 2–3 天 |
| 9 | 每 3 天更新 tracking 表（§4） | 本文件 §4 | 持续 |

---

## 2. 各渠道帖子最终稿

> 所有帖子统一附：仓库链接 + 合规声明（仅个人已购内容、个人离线阅读、不绕过付费墙）。

### 2.1 Show HN（英文，~200 词）

```text
Show HN: Zhihu Salt-Novel Downloader – a minimal CLI for your purchased Zhihu content

Zhihu (知乎) hosts paid "salt-novel" (盐选) columns. There was no simple way to
export content you have legitimately purchased for offline reading.

This is a minimal, dependency-light Python CLI (one package, ~5 files):

- QR-code login with the official flow (cookies saved locally)
- Download single sections or whole columns (market/paid_column links)
- Export to txt / md / epub
- Rate-limited by default (2 req/s), no paywall bypass, purchased content only

Everything is synchronous and readable on purpose. MIT licensed.

https://github.com/xfengyin/zhihu-salt-novel-downloader

Compliance: only content you purchased/subscribed to, personal offline use,
no redistribution, respects Zhihu's ToS (see README).
```

**发帖要点**：标题用 "Show HN:"；正文贴上面文本；发完立即在评论区自评一句
（如：欢迎指正，尤其签名/限速部分）。

### 2.2 Reddit r/Python（英文）

```text
Title: [P] A minimal CLI to export purchased Zhihu salt-novel content (qr-login,
txt/md/epub, rate-limited, MIT)

Body:
I built a small synchronous Python CLI for Zhihu (知乎) paid columns: scan to log
in, then download sections or whole columns you purchased, export to txt/md/epub.
No scraping tricks – it uses the same signed requests a normal browser session
would, is rate-limited by default (2 req/s), and explicitly does NOT bypass
paywalls (purchased content only, personal offline use).

Repo: https://github.com/xfengyin/zhihu-salt-novel-downloader

Happy to hear feedback on the code – it's deliberately minimal and readable.
```

### 2.3 Reddit r/selfhosted（英文，配合 Web UI）

```text
Title: Self-host a tiny web UI to export your purchased Zhihu salt-novel content

Body: zhihu-downloader ships an optional minimal FastAPI web UI (python -m
zhihu_downloader web). Scan to log in, paste a link, download the epub. 1-minute
setup, MIT, rate-limited by default. https://github.com/xfengyin/zhihu-salt-novel-downloader
```

### 2.4 Awesome 列表投稿（一句话描述模板）

> 投稿 = 在列表 README 的合适分类下加一行 + 提 PR。以下文案按列表微调。

```text
zhihu-salt-novel-downloader - Minimal CLI to export your purchased Zhihu
salt-novel content (QR login, txt/md/epub, rate-limited, MIT).
https://github.com/xfengyin/zhihu-salt-novel-downloader
```

候选列表（详见 PROMOTION §2）：
- awesome-zhihu（搜 "awesome zhihu" 找活跃列表）
- awesome-downloader / awesome-scraper 类
- awesome-selfhosted（配合 Web UI 说明）

### 2.5 掘金（中文技术社区）

```markdown
# 我写了个极简知乎盐选小说下载器（v4）：扫码登录 + txt/md/epub 导出

知乎盐选付费专栏买了之后只能在 App 里看，想导出到阅读器很麻烦。
我写了个极简 Python CLI（约 5 个文件，同步、可读、易维护）：

- 扫码登录（官方流程，Cookie 存本地）
- 下载盐选单章节 / 整个专栏（market/paid_column 链接）
- 导出 txt / md / epub
- 默认限速 2 请求/秒，不绕过付费墙，仅限已购内容个人离线阅读

仓库：https://github.com/xfengyin/zhihu-salt-novel-downloader

代码刻意保持简单——同步、无异步魔法，适合学习与二次修改。
MIT 协议，欢迎提 issue / PR。
```

### 2.6 知乎（中文，作者身份分享）

```markdown
分享一个自用的知乎盐选下载小工具（极简 v4）：

扫码登录 → 下载已购章节/专栏 → 导出 txt/md/epub。
默认限速、不绕过付费墙，仅限自己已购买内容个人离线阅读。

GitHub：https://github.com/xfengyin/zhihu-salt-novel-downloader
（按仓库 README 的合规声明使用）
```

---

## 3. 截图 / 录屏建议

- **首选 asciinema 录屏**（终端真演示，可嵌入 README）：
  1. 本地登录一个已购章节（或 mock 流程），`asciinema rec demo.cast` 录制：
     `--version` → `qr-login` → `download --format epub` → `--help`；
  2. `asciinema upload demo.cast` 得到链接，README「终端演示」替换为
     `[![asciicast](https://asciinema.org/a/<id>.svg)](https://asciinema.org/a/<id>)`；
  3. 注意：录屏内**不要出现真实 Cookie / 账号信息**（可提前用假账号或裁剪）。
- **若用静态截图**（README 或帖子配图）：
  - 终端配色用默认或深色主题；字号 ≥ 14；窗口宽度 ≥ 100 列；
  - 图片宽度 800–1200px，PNG 或 WebP；
  - 截图前清理无关输出，突出「命令 → 结果」；
  - 不 P 图、不造假输出。
- **帖子配图**：一张「下载成功 + 导出文件列表」截图最有效；不要用网图。

---

## 4. 发帖后 tracking 表

> 每发一个渠道，填一行。**star 数据**在发帖后第 1/3/7 天记录（GitHub Insights）。

| 渠道 | 链接 | 发帖日期 | 浏览/阅读 | 点赞/评分 | 评论 | 带来的 star | 备注 |
|------|------|----------|-----------|-----------|------|-------------|------|
| Show HN | | | | | | | |
| Reddit r/Python | | | | | | | |
| Reddit r/selfhosted | | | | | | | |
| awesome-zhihu | | | | | | | |
| awesome-downloader/scraper | | | | | | | |
| awesome-selfhosted | | | | | | | |
| 掘金 | | | | | | | |
| 知乎 | | | | | | | |
| V2EX（可选） | | | | | | | |

**复盘**（发帖 2 周后，回填到 PROMOTION §8）：
- 哪个渠道转化最好？哪个最差？
- 评论里被问最多的问题是什么？（→ 下一版 FAQ / README 补充）

---

## 5. 合规与纪律

- 每个渠道**只发一次**；被删/被拒不重发、不申诉纠缠。
- 帖子必须保留合规声明；不得引导「破解」「白嫖」。
- 不在任何渠道刷 star / 刷赞 / 组织互刷。
- 若平台规则要求，先读平台规则（如 Reddit self-promotion 比例 < 10%）。

---

*随仓库维护；发布前先跑 `docs/RELEASE_CHECKLIST.md`。*
