# 冲高星行动清单（Promotion Playbook）

> 目标：让 zhihu-salt-novel-downloader 从当前水位（v4.2.0 起）稳步冲高。
> 本文档是执行清单：**每一条都给出「做什么 / 怎么做 / 验收标准」**，全部可离线准备，
> 合入 master 后按节奏一次性执行。原则：真实、合规、可持续，不刷星、不造假。

---

## 0. 发布前 Checklist（每次发版前跑一遍）

> 完整版见 [`docs/RELEASE_CHECKLIST.md`](RELEASE_CHECKLIST.md)（六块：测试 / CI / README / Release notes / 资产验证 / 合规）。
> 以下为快速版；勾选项 = M1–M3 已落地基建（随 v4.2.0 合入），未勾项 = 待执行动作。

- [x] 版本号三处同步：`simple/pyproject.toml`、`simple/zhihu_downloader/__init__.py`、`simple/zhihu_downloader/webapp.py`
- [x] `cd simple && python -m pytest -q` 全绿
- [x] `python -m zhihu_downloader --help` / `--version` 输出正常（`--version` 自 v4.2.0 支持）
- [x] README 双语（`simple/README.md` / `simple/README.en.md`）与本次变更同步
- [x] Badge 链接有效（CI / Release / Stars / License）
- [x] CI（`.github/workflows/ci-simple.yml`）在 master 上绿
- [x] Release notes 按 §5 规范写好，贴到 GitHub Release
- [ ] 打 `v4.x.y` 标签（触发 release-simple.yml 构建发布）

---

## 1. README 要点清单

README 是转化率最高的「广告位」。对照检查（当前版本已满足大部分）：

| # | 要点 | 验收标准 | 状态 |
|---|------|----------|------|
| 1 | 一句话价值主张 | 标题下 2 行内说清「是什么、解决什么」 | ✅ 已具备 |
| 2 | Badge 行 | CI / Release / Stars / License 四件套 | ✅ v4.2.0 |
| 3 | 特性列表 | 8 条以内、emoji + 加粗、每条一行 | ✅ v4.2.0 |
| 4 | 演示/截图 | 终端示例（模拟）或真实 asciinema 录屏 | ✅ 终端演示（模拟） |
| 5 | 安装 ≤3 行 | 复制即用 | ✅ |
| 6 | 用法 ≤10 行 | 登录 + 下载 + 导出即可跑通 | ✅ |
| 7 | 二维码登录流程 | 图示/步骤说明清楚 | ✅ v4.2.0 |
| 8 | FAQ | 覆盖 403 / 二维码过期 / 链接类型 | ✅ |
| 9 | 合规声明 | 仅个人已购内容、限速、不绕过付费墙 | ✅ |
| 10 | License | MIT | ✅ |

**升级项（后续可选，状态更新）**：
- [ ] 用 asciinema 录一段真实终端演示，替换「模拟」标注（前提：可正常登录并下载一个已购章节）——**待执行**
- [ ] 增加「Star 理由」一行：`如果这个工具帮到你，点个 ⭐ 支持维护`（放在 README 末尾 License 前）——**待执行**

---

## 2. Awesome 列表投稿清单

| 列表 | 网址 | 投稿方式 | 条件 / 注意 | 状态 |
|------|------|----------|-------------|------|
| awesome-zhihu | github.com/*（搜 "awesome zhihu"） | 提 PR 改 README | 附合规声明；项目须可跑通 | ⬜ 待执行（README 英文版已就绪 ✅） |
| awesome-downloader / awesome-scraper | github.com/*（搜 "awesome downloader"） | 提 PR 或 issue 自荐 | 强调「扫码登录 + 签名 + 限速」差异化 | ⬜ 待执行（差异化卖点已写入 README ✅） |
| awesome-python（筛选列表） | github.com/vinta/awesome-python | 一般只收知名库，机会小 | 可作为远期目标 | ⬜ 观察 |
| awesome-selfhosted | github.com/awesome-selfhosted/awesome-selfhosted | 提 PR | 需提供自托管 Web UI 说明 | ⬜ 待执行（Web UI 已具备 ✅） |

**通用投稿纪律**：
1. 每个列表只投一次；被拒不纠缠、不重复提交。
2. 投稿文案用英文，一句话描述 + 仓库链接 + 合规声明链接。
3. 投稿前确保 README 英文版完整（本项目已具备 ✅）。

---

## 3. 英文社区帖子草稿

> 纪律：每个社区只发一次；发帖即代表项目公开亮相，务必先合入 v4.2.0 全部内容。
> 帖子统一附：仓库链接 + 合规声明（仅个人已购内容）。
>
> **状态更新（M4）**：v4.2.0 已发布，草稿全部就绪，**待执行发帖**（建议在 v4.2.0 Release notes 上线后一周内完成 HN + Reddit 两帖）。

### 3.1 Hacker News —— Show HN 草稿

```
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

### 3.2 Reddit r/Python 草稿

```
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

### 3.3 Reddit r/selfhosted 草稿（配合 Web UI）

```
Title: Self-host a tiny web UI to export your purchased Zhihu salt-novel content

Body: zhihu-downloader ships an optional minimal FastAPI web UI (python -m
zhihu_downloader web). Scan to log in, paste a link, download the epub. 1-minute
setup, MIT, rate-limited by default. https://github.com/xfengyin/zhihu-salt-novel-downloader
```

### 3.4 中文社区（可选，二次传播）

- 知乎想法/回答：以「工具作者」身份分享，附合规边界说明。
- V2EX：分享帖 + 讨论帖各一篇，注意平台规则（不刷屏）。

---

## 4. Issue 模板

> **状态更新（M4）**：✅ **已落地** `.github/ISSUE_TEMPLATE/bug_report.md` 与 `feature_request.md`（中文为主），
> GitHub 新 Issue 页面会自动使用。以下内容保留为参考副本（与落地文件同步维护）。

### 4.1 `bug_report.md`

```markdown
---
name: Bug report
about: 报告问题，帮助改进
title: "[Bug] "
labels: bug
---

**描述问题**（Describe the bug）
发生了什么？预期是什么？

**复现步骤**（To reproduce）
1. 命令：`python -m zhihu_downloader ...`
2. 操作系统 / Python 版本：
3. 日志或报错输出（脱敏后粘贴）：

**环境**（Environment）
- 版本：`python -m zhihu_downloader --version` 的输出
- 系统：Windows / macOS / Linux

**其他**（Anything else）
Cookie 相关敏感信息请打码。
```

### 4.2 `feature_request.md`

```markdown
---
name: Feature request
about: 建议新功能
title: "[Feature] "
labels: enhancement
---

**要解决的问题**（What problem does it solve？）

**期望行为**（Describe the solution you'd like）

**替代方案**（Alternatives you considered）

**合规自查**（Compliance check）
- [ ] 该功能不涉及绕过付费墙 / 权限校验
- [ ] 该功能仅面向已授权内容
```

---

## 5. Release notes 规范

> 发版流程与检查见 [`docs/RELEASE_CHECKLIST.md`](RELEASE_CHECKLIST.md)。

格式（中文为主 + 英文一句话摘要，便于海外传播）：

```
## v4.2.0 (2026-xx-xx)

### 新增（New）
- ...
### 改进（Improved）
- ...
### 修复（Fixed）
- ...
### 合规（Compliance）
- ...

English summary: one or two sentences describing the release.
```

**示例（v4.1.0 风格）**：

```
## v4.1.0

### 新增
- simple 目录新增 CI（.github/workflows/ci-simple.yml）：push/PR 到 master 自动跑 pytest
### 改进
- 版本号统一为 4.1.0（pyproject / __init__ / webapp 三处同步）
- README 中英文顶部增加 CI badge

English: v4.1.0 adds GitHub Actions CI for the simple package and syncs versioning.
```

**规范要求**：
- 每条 ≤ 一行，动词开头（新增/改进/修复）；
- 涉及行为的变更必须写清「对用户的影响」；
- 合规类改动单独成节，突出「仅已购内容 / 限速 / 不绕过付费墙」。

---

## 6. SEO 关键词

### 6.1 关键词表

| 语言 | 关键词 |
|------|--------|
| 中文 | 知乎盐选小说下载、盐选小说下载器、知乎专栏下载、盐选付费文章导出、知乎下载工具 |
| 英文 | zhihu salt novel downloader, zhihu paid column export, zhihu downloader, xiazai zhihu, zhihu yanxuan downloader |
| 长尾 | 知乎盐选 epub 下载、zhihu salt novel epub, export purchased zhihu content offline |

### 6.2 放置位置

| 位置 | 用法 |
|------|------|
| GitHub repo description | 含「知乎盐选小说下载器 / Zhihu Salt-Novel Downloader」 |
| GitHub topics | `zhihu` `downloader` `novel` `epub` `python` `cli` `scraper`（≤20 个） |
| README 标题与首段 | 自然出现主关键词各 1 次，不堆砌 |
| Release notes | 每次发版标题含版本号 + 主关键词 |
| 项目主页/博客（若有） | 用关键词写 1 篇「为什么做这个工具」 |

### 6.3 GitHub 搜索优化

- description 控制在 120 字符内，开头放主关键词；
- topics 用 GitHub 官方建议标签；
- 保持提交活跃（每周至少 1 次），提升「最近更新」曝光。

---

## 7. 发布节奏

- **小版本（patch/minor）**：每周最多一次，内容 = 修复 + 小改进 + README 完善。
- **大版本（major）**：每月一次，内容 = 新功能 + 性能/架构改进。
- **发布日动作**：
  1. 跑 §0 Checklist；
  2. 打 tag `v4.x.y`（触发自动构建发布）；
  3. 按 §5 写 Release notes；
  4. 执行 §2/§3 中「本版本对应」的投稿动作（如适用）。

## 8. 复盘

每个里程碑结束后回答 3 个问题，写入本文件末尾：
1. 这个版本带来了多少新 star？（GitHub insights 数据）
2. 哪条渠道转化最好？（README / HN / Reddit / Awesome）
3. 下一版最该补的短板是什么？（对照 §1 升级项）

---

## 9. 下一步外部投稿清单（状态跟踪）

> **M5 更新：准备完成** ✅ —— 执行包已就绪：
> - 帖子**最终稿**、发布顺序、tracking 表、截图/录屏建议 → [`docs/LAUNCH_PACK.md`](LAUNCH_PACK.md)；
> - 贡献指南 → `CONTRIBUTING.md`（仓库根目录）。
>
> **M6 更新：发布与资产验证已执行** ✅ —— 详见 [`docs/LAUNCH_LOG.md`](LAUNCH_LOG.md) §1。
> 以下为**待执行的对外动作**，每完成一项勾选并记录日期。

| # | 动作 | 前置条件 | 状态 | 完成日期 |
|---|------|----------|------|----------|
| 1 | 打 tag `v4.2.0` 发布（触发 release-simple.yml） | §0 全绿 | ✅ 已执行（Release `v4.2.0` 已存在，两资产 URL 均 HTTP 200） | 2026-08-24 |
| 2 | 发布后验证 Linux/Windows 资产（见 RELEASE_CHECKLIST §7、LAUNCH_LOG §1） | 动作 1 | ✅ 已执行（下载 + SHA-256 + zip 完整性通过；运行时验证受环境限制待目标环境补跑，见 LAUNCH_LOG §1） | 2026-08-24 |
| 3 | Show HN 发帖（最终稿见 LAUNCH_PACK §2.1） | 动作 1 完成 | ⬜ 待执行 | |
| 4 | Reddit r/Python 发帖（最终稿见 LAUNCH_PACK §2.2） | 动作 1 完成 | ⬜ 待执行 | |
| 5 | Reddit r/selfhosted 发帖（最终稿见 LAUNCH_PACK §2.3） | 动作 1 完成 | ⬜ 待执行 | |
| 6 | Awesome 列表投稿（一句话文案见 LAUNCH_PACK §2.4，候选见 §2） | 动作 1 完成 | ⬜ 待执行 | |
| 7 | GitHub topics / description SEO 设置（§6.2/6.3） | 动作 1 完成 | ⬜ 待执行 | |
| 8 | 中文社区：掘金（LAUNCH_PACK §2.5）+ 知乎（§2.6）+ V2EX（可选） | 动作 3–4 完成 | ⬜ 待执行 | |
| 9 | asciinema 录屏替换「模拟」标注（建议见 LAUNCH_PACK §3） | 可正常登录下载已购章节 | ⬜ 待执行 | |
| 10 | README 末尾加「Star 理由」一行（§1 升级项） | 无 | ⬜ 待执行 | |

> 发帖后按 LAUNCH_PACK §4 tracking 表记录，两周后复盘（§8）。

---

*本文档随仓库维护；所有动作以「真实、合规、可持续」为前提。*
