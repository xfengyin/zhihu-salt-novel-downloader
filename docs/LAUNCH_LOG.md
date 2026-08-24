# 发布与投稿执行日志（Launch Log）

> 用途：记录 v4.x.y 发布的**资产验证结果**与**外部投稿执行情况**（发帖日期/链接/效果）。
> 发布顺序与最终稿见 [`docs/LAUNCH_PACK.md`](LAUNCH_PACK.md)；待办清单见 [`docs/PROMOTION.md`](PROMOTION.md) §9。
> 原则：**如实记录**——验证失败、环境受限都要写明，不粉饰。

---

## 1. 发布验证记录

### v4.2.0（2026-08-24）

**Release 存在性**：✅ 已确认 —— GitHub Release `v4.2.0` 存在，
两个资产 URL 均返回 HTTP 200（`release-simple.yml` 构建成功）。

| 资产 | 下载地址 | 大小 | SHA-256 | 完整性 | 运行时验证 |
|------|----------|------|---------|--------|------------|
| Linux x64 (`zhihu-downloader-simple-4.2.0-linux-x64.tar.gz`) | [GitHub Releases](https://github.com/xfengyin/zhihu-salt-novel-downloader/releases/download/v4.2.0/zhihu-downloader-simple-4.2.0-linux-x64.tar.gz) | 40,988,894 B | `2a1afd794af5aac05b32554a21954e0e72d7a43e21252469eff5ce062c43ce27` | ✅ tar.gz 解压正常，含 `zhihu-downloader`（41,319,952 B） | ⚠️ 见下 |
| Windows x64 (`zhihu-downloader-simple-4.2.0-windows-x64.zip`) | [GitHub Releases](https://github.com/xfengyin/zhihu-salt-novel-downloader/releases/download/v4.2.0/zhihu-downloader-simple-4.2.0-windows-x64.zip) | 21,159,686 B | `53176e1208cc53e78af553c5603fd63668a2864e8b7e8931343d07e40d381c9b` | ✅ `testzip()` 通过，含 `zhihu-downloader.exe`（21,396,886 B） | ⚠️ 见下 |

**执行过的命令（Linux 资产）**：

```bash
# 下载
curl -sSL -o zhihu-linux.tar.gz \
  "https://github.com/xfengyin/zhihu-salt-novel-downloader/releases/download/v4.2.0/zhihu-downloader-simple-4.2.0-linux-x64.tar.gz"
# 解压
tar -xzf zhihu-linux.tar.gz -C zhihu-linux
# 尝试运行
./zhihu-downloader --version
./zhihu-downloader --help
```

**执行过的命令（Windows 资产）**：

```bash
curl -sSL -o zhihu-win.zip \
  "https://github.com/xfengyin/zhihu-salt-novel-downloader/releases/download/v4.2.0/zhihu-downloader-simple-4.2.0-windows-x64.zip"
python -m zipfile -t zhihu-win.zip   # zip 完整性
```

**运行时验证结论（重要）**：

- ⚠️ **Linux 二进制**：在本次验证环境（Debian 12, GLIBC 2.36）无法运行——
  PyInstaller 一文件二进制由 ubuntu-24.04（GLIBC 2.39）构建，报错
  `libpython3.12.so.1.0: version 'GLIBC_2.38' not found`。
  **结论**：资产本身完整（解压/哈希均通过），运行时验证需在 **GLIBC ≥ 2.38**
  的 Linux 主机（如 ubuntu-24.04 / Debian 13 / 主流发行版）执行，预期输出：
  `--version` → `zhihu-downloader 4.2.0`；`--help` → 三个子命令 + `--version` 选项。
- ⚠️ **Windows 二进制**：本环境为 Linux，无法执行 `.exe`。
  **结论**：zip 完整、包含 `zhihu-downloader.exe`；运行时验证需在
  **Windows 10/11 x64** 主机执行（命令同 Linux：`--version` / `--help`）。
- ✅ 本地源码冒烟（同版本代码）：`python -m zhihu_downloader --version` → `zhihu-downloader 4.2.0`；
  `--help` 正常（见下方 pytest/冒烟验证）。

**待办**：在目标环境（GLIBC ≥ 2.38 的 Linux / Windows 10/11）补跑 `--version` / `--help`，
确认后在本节勾选 ⬜ → ☑ 并注明环境。

### Release 描述更新（M7，2026-08-24）

✅ 已通过 GitHub API `PATCH /releases/375758922` 更新 v4.2.0 Release body：
- 内容：英文 Announcement + 中文简介 + Downloads（Linux/Windows 资产链接 + 源码安装）+ 合规说明（中英）+ Changelog 链接
- 结果：body 更新成功（1297 字符），含「English Announcement / 中文简介 / Downloads / 合规 / no paywall bypass」
- Release 页面：https://github.com/xfengyin/zhihu-salt-novel-downloader/releases/tag/v4.2.0

### 投稿文件已就绪（M7，2026-08-24）

✅ 6 份帖子最终稿已拆分为独立文件（可直接复制发布）：

| 渠道 | 文件 |
|------|------|
| Show HN | [`docs/posts/hn.md`](posts/hn.md) |
| Reddit r/Python | [`docs/posts/reddit_python.md`](posts/reddit_python.md) |
| Reddit r/selfhosted | [`docs/posts/reddit_selfhosted.md`](posts/reddit_selfhosted.md) |
| Awesome 投稿 | [`docs/posts/awesome.md`](posts/awesome.md) |
| 掘金 | [`docs/posts/juejin.md`](posts/juejin.md) |
| 知乎 | [`docs/posts/zhihu.md`](posts/zhihu.md) |

---

## 2. 待执行的外部投稿清单

> 材料全部就绪（LAUNCH_PACK 最终稿 + PROMOTION §9）。执行顺序见 LAUNCH_PACK §1。

| # | 动作 | 材料位置 | 状态 |
|---|------|----------|------|
| 1 | 目标环境补跑二进制 `--version` / `--help` | 本节 §1 待办 | ⬜ 待执行 |
| 2 | Show HN 发帖 | LAUNCH_PACK §2.1 | ⬜ 待执行 |
| 3 | Reddit r/Python 发帖 | LAUNCH_PACK §2.2 | ⬜ 待执行 |
| 4 | Reddit r/selfhosted 发帖 | LAUNCH_PACK §2.3 | ⬜ 待执行 |
| 5 | Awesome 列表投稿（3 候选） | LAUNCH_PACK §2.4 | ⬜ 待执行 |
| 6 | 掘金 / 知乎 / V2EX（可选） | LAUNCH_PACK §2.5–2.6 | ⬜ 待执行 |
| 7 | GitHub topics / description SEO | PROMOTION §6.2/6.3 | ⬜ 待执行 |
| 8 | asciinema 录屏替换「模拟」标注 | LAUNCH_PACK §3 | ⬜ 待执行 |

---

## 3. 实际发帖 tracking

> 每发一个渠道填一行；star 数据在发帖后第 1/3/7 天记录（GitHub Insights）。

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

**两周复盘**（发帖后回填）：哪个渠道转化最好？评论被问最多的问题？（→ FAQ/README 补充）

---

*随仓库维护；记录务必真实。*
