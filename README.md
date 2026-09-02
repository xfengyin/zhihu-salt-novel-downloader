# 知乎盐选小说下载器

> **把你已购买的盐选小说，变成能舒服躺在 Kindle / Kobo / Boox 上的精排电子书。**
> 双击即用 · 扫码登录 · 断点续传 · 追更增量 · 零构建本地 Web UI

[![Release](https://img.shields.io/github/v/release/xfengyin/zhihu-salt-novel-downloader?label=release&color=blue)](https://github.com/xfengyin/zhihu-salt-novel-downloader/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/xfengyin/zhihu-salt-novel-downloader/total?color=brightgreen)](https://github.com/xfengyin/zhihu-salt-novel-downloader/releases)
[![CI](https://github.com/xfengyin/zhihu-salt-novel-downloader/actions/workflows/ci.yml/badge.svg)](https://github.com/xfengyin/zhihu-salt-novel-downloader/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](#通过-pip-安装)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)](#-快速上手)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

一个**单机自用的离线备份工具**：CLI 内核 + 本地 Web 界面装进同一个包，发布为单文件可执行程序。
不搭服务器、不碰数据库、不向任何第三方上传内容——正文与 Cookie 只发给知乎本身（下载必需）。

```text
$ zhihu-downloader download --url "https://www.zhihu.com/market/paid_column/…" -f epub -o ~/Books
[█████████░░░░░░░░░░░░░░] 24/47 (51%) 第24章：夜航船          ← 单行刷新进度（含章节标题）
✅ 夜航船（共 47 章）
   /home/you/Books/夜航船.epub                                 ← stdout 只输出结果，可直接管道
```

---

## ✨ 为什么是它

| | |
|---|---|
| 🖱️ **双击即用** | 下载单文件 EXE 双击即进图形界面（无参数启动 = 起本地服务 + 自动开浏览器），全程不用敲命令 |
| 🔌 **最抗失效** | `doctor` 本地签名自检，一句话分流「Cookie 掉了（重新登录）」vs「签名算法过期（升级工具）」；盐选垂直工具死于一次签名轮换是常态，本项目把它变成可诊断、可升级的明路 |
| 💾 **断点续传 + 自愈** | 逐章落盘，断网 / 关窗 / 断电后重跑同一链接只补未完成章节；章节缓存损坏自动重取，不用手工清状态 |
| 📖 **EPUB 精排** | 封面页 + 两级目录 + 番外/作者说归入附录 + 稳定 identifier（同一本书多次导出可被阅读器合并为同一本书）；墨水屏友好 |
| 🔄 **追更** | 连载书进书架，作者更新了点「追更」：只抓新增章节，重排整本 |
| 🛡️ **安全是审出来的** | 两轮对抗审查（代码质量 + 攻击面）驱动的安全加固，全部结论冻结为可执行门禁（见[质量保障](#-质量保障)）：Cookie 跨域漂流、SSRF 解析差分、CSRF-lite、控制台注入面逐项封堵 |

## 🚀 快速上手

### 下载单文件程序（不需要装 Python）

到 [Releases](https://github.com/xfengyin/zhihu-salt-novel-downloader/releases/latest) 取对应平台的产物：

| 平台 | 产物 | 启动 |
|---|---|---|
| Windows x64 | `zhihu-downloader-5.0.0-windows-x64.exe` | **双击**（首次运行见下方 SmartScreen 说明） |
| macOS Apple Silicon | `zhihu-downloader-5.0.0-macos-arm64` | `chmod +x` 后运行 |
| Linux x64（glibc ≥ 2.35） | `zhihu-downloader-5.0.0-linux-x64` | `chmod +x` 后直接运行 |

启动后：页面里点「扫码登录」→ 手机知乎 App 扫一扫 → 粘贴盐选链接 → 选 `epub` → 下载完成后把文件拷进阅读器。

- **Windows**：本项目无代码签名证书，未签名的 PyInstaller 包会被 SmartScreen 拦——点「更多信息」→「仍要运行」。
  想核实完整性：`certutil -hashfile zhihu-downloader-5.0.0-windows-x64.exe SHA256` 对照 Release 附件 `SHA256SUMS.txt`。
- **macOS**：右键 →「打开」一次即可；或 `xattr -d com.apple.quarantine ./zhihu-downloader-5.0.0-macos-arm64`。
- **Linux**：产物在 Ubuntu 22.04 runner 上构建（glibc 2.35 地板），更老的发行版请走 pip 安装。
- **Intel Mac**：暂无 x64 构建产物，用 `pip install` 方式（下方）。

### 通过 pip 安装

```bash
pip install "git+https://github.com/xfengyin/zhihu-salt-novel-downloader.git@v5.0.0"
zhihu-downloader gui          # 起本地服务并自动开浏览器（默认 127.0.0.1:3000）
```

运行时依赖只有 5 个：`requests` / `beautifulsoup4` / `fastapi` / `uvicorn` / `ebooklib`，Python ≥ 3.10。
可选 `pip install ".[browser]"` 启用从 Chrome / Edge / Firefox 直接导入知乎 Cookie。

## 📦 功能一览

| 能力 | 说明 |
|---|---|
| 扫码登录 | 知乎 App 扫码，Cookie 自动落盘（`O_CREAT`+`O_EXCL`、`0600`，创建瞬间即私有权限） |
| Cookie 导入 | 三种格式自动识别：JSON 对象 / Netscape `cookies.txt` / `k=v; k2=v2` 原始串 |
| 断点续传 | 逐章落盘到 `<输出目录>/.zhihu_state/`；某章最终失败时中止整本、已完成章节全部保留，重跑同一命令自动续传（错误消息也会这么指引） |
| 章节级进度 | CLI 单行进度条 + Web SSE：当前第几章 / 总数 / 章节标题，不用手动刷新 |
| 限速内并行 | 整体节奏由客户端限速钳制（默认 2 请求/秒，跨线程预约时间槽）；`--workers` 只让等待中的请求互相重叠，**不提高每秒请求数** |
| 失败重试 | 网络错误与 429/5xx 指数退避重试 3 次（1/2/4 秒）；403 不重试，直接给可操作的中文提示 |
| EPUB 精排 | 封面页 + 两级目录 + 稳定 identifier + 内嵌排版 CSS；番外与「作者说」自动归入「附录」节点 |
| MD / TXT 导出 | MD 保留 `h2`/`h3` 层级、列表、引用、图片引用；TXT 拍平为纯文本 |
| 书架 + 追更 | `~/.zhihu_downloader/shelf.json` 记录已下载章节，增量比对只下新章；移除条目时一并清理该书断点缓存 |
| doctor 诊断 | Cookie 存在与权限、`z_c0` / `zse_ck` / `d_c0`、**签名自检**、限速合理性、网络探测、断点磁盘占用；区分「Cookie 失效」与「签名轮换」两条排障路径 |
| 新版本提示 | 启动与 doctor 时查 GitHub Releases（10 秒超时、失败静默、输出经净化防控制台注入），`--no-update-check` 可关 |
| 零构建 Web UI | 原生 HTML/CSS/JS，无 Node、无打包器；深浅色主题，SSE 断线自动降级为轮询 |

## 🔗 支持的链接

| 链接类型 | 示例 | 支持 | 说明 |
|---|---|---|---|
| 盐选专栏（整本） | `https://www.zhihu.com/market/paid_column/1234567890123456789` | ✅ | 先抓目录再逐章下载，需要有效登录 Cookie |
| 盐选单章节 | `https://www.zhihu.com/market/paid_column/1234/section/5678` | ✅ | 只下该章；要整本请给专栏目录页链接 |
| 公开回答 | `https://www.zhihu.com/question/123456/answer/789012` | ✅ | 按单篇文章下载正文 |
| 知乎专栏文章 | `https://zhuanlan.zhihu.com/p/123456` | ✅ | 同上，独立识别为 `zhuanlan` |
| 仅 APP 内阅读 | `https://story.zhihu.com/manuscript/paid_column/1234/5678` | ❌ | 需要知乎移动端私有 `mst`/`xsec` 设备签名，本项目**不会**去逆向（见红线）。**换成网页版链接就能下**，替换规则见下 |
| 非知乎链接 | `https://example.com/...` | ❌ | 只接受 `zhihu.com` 及其子域 |

**story 链接怎么换成网页版**（把 ID 照抄进模板即可）：

- 整本：`story.zhihu.com/manuscript/paid_column/1234` → `www.zhihu.com/market/paid_column/1234`
- 单章：`story.zhihu.com/manuscript/paid_column/1234/5678` → `www.zhihu.com/market/paid_column/1234/section/5678`

嫌手工改麻烦就直接贴原链接：工具会报错并**把替换好的网页版链接整条打出来**，复制重贴即可。
前提是该内容网页端也可读且你已购；纯 APP 独占内容请直接在 App 内阅读。

逐条识别规则见 [docs/SUPPORT_MATRIX.md](docs/SUPPORT_MATRIX.md)。

## ⌨️ 命令行速查

```bash
zhihu-downloader login [--browser]              # 扫码（终端打印二维码图片路径）；--browser 从浏览器导入
zhihu-downloader download --url U [-f txt|md|epub] [-o DIR] [--no-resume]
                              [--rate-limit R] [--workers N] [--batch-file F]
zhihu-downloader shelf [list|remove ID|update [--all]]    # 书架：列出 / 删除条目（含断点清理）/ 追更
zhihu-downloader doctor [--no-network] [--cookie-file F]  # 诊断（Cookie、签名自检、新版本提示）
zhihu-downloader gui [--host H] [--port P] [--no-browser] # 起本地服务并自动开浏览器（端口被占自动 +1 重试 3 次）
```

裸启动（不给任何子命令）等价于 `gui`——这就是双击 EXE 即进图形界面的原因。

```bash
zhihu-downloader login                       # 1. 扫码登录
zhihu-downloader doctor                      # 2. 自检：缺 d_c0、权限过松都会直说
zhihu-downloader download --url "https://www.zhihu.com/market/paid_column/1234" -f epub -o ~/Books
zhihu-downloader shelf update --all          # 3. 追更：只下新增章节
```

输出契约：`stdout` 只放可管道消费的结果（书名与文件清单），进度条与告警走 `stderr`——
`download ... > files.txt` 拿到的是干净的文件清单。不写 `-o` 时 CLI 默认落在 `./output/`，GUI 默认 `~/.zhihu_downloader/output/`。

## 🛡️ 安全与隐私边界

**数据流向**：正文与 Cookie 只发给知乎本身；对外唯一另一个请求是启动时向 GitHub 查一次最新版——
固定地址、不带 Cookie / 书名 / 链接 / 用户标识，`--no-update-check` 可关。

**本地服务**：GUI 只是本机进程，默认监听 `127.0.0.1`。写接口校验请求来源（Origin/Referer 指向本机），
`/api/cookies` 只回布尔不回传 Cookie 值，导出文件按任务登记白名单取用，全站响应带 CSP / `nosniff` /
`X-Frame-Options: DENY` / `no-store`。它**没有账号体系**，所以「谁能连到这个端口」就等于「谁能用你的登录态」：

- 用 `--host` 绑到非回环地址时，启动告警会**逐条列出四件事**：① 用你的知乎账号发起下载（花你的配额、写你的硬盘）；
  ② 拉走你已导出的全部文件；③ 覆盖或清除你的登录 Cookie；④ 借本工具访问你内网里的其它服务
  （路由器后台、云主机 metadata、只监听了本机的端口）。只想本机用就别改 `--host`。
- 粘贴的链接里含 `@` 或反斜杠时会被直接拒绝（400 / 中文报错）。**这是保护，不是 bug**：这类写法是
  「闸门看到的域名」与「HTTP 栈真正连出去的主机」不一致的经典差分载荷，本项目让闸门与 HTTP 栈用同一个
  解析器并硬拒这类字符，代价就是它们永远进不了下载队列。

## ⚖️ 合规与使用限制

- **仅下载已授权内容**：只可下载你本人已购买、已订阅或已获授权访问的盐选内容，仅用于个人离线备份。
- **不绕过付费墙**：不破解、不绕过任何付费墙或权限校验；未购买 / 无权限的内容下载不到。
- **默认限速**：默认 2 请求/秒，合理区间 **0.5~5** 由 `doctor` 单源定义，超界一律钳制（填 0 也不会「不限速」）。
  本项目刻意**不与风控赛跑**——这是「能长期用下去」的代价，不做多倍速抓取。
- **禁止再分发**：禁止把下载内容用于传播、上传网盘或资源站、商业用途；请勿去除版权声明。
- **遵守服务条款**：请遵守[《知乎用户协议》](https://www.zhihu.com/terms)及相关法律法规。

> 使用即表示你同意以上限制；因违规使用产生的法律风险由使用者自行承担。

### 我们「永不做」（信任承诺）

写进[路线图红线](docs/ROADMAP.md)的产品边界，任何版本都不会出现：

- ❌ 绕过付费墙 / 下载未购内容
- ❌ 逆向知乎 APP 端 `mst` / `xsec` 设备签名，抓「仅 APP 内阅读」内容
- ❌ 代理池 / 多账号轮换 / 任何对抗风控的能力
- ❌ 内置资源库、搜索盗版源、任何分发或营利功能
- ❌ 抹除权利标识：清洗只针对平台自带的推广性脚标（`@知乎`、裸 `zhihu.com`、块首独立的 `来源：` 短行、
  `相关推荐`），不是作者署名或版权段落。拿本项目当「去水印工具」不在用途范围内。

## 🧪 质量保障

这个版本由多智能体团队构建，两轮**对抗审查**（代码质量 + 攻击面）驱动收尾，全部结论冻结为可执行门禁：

- **896 个离线测试**（mock 只在 `requests.Session` 边界，零真实网络），ruff 全仓净
- **11 项验收门禁**（`scripts/acceptance.py`）：测试 / lint / 发布校验 / 依赖铁律 / 版本单源 / GUI 冒烟 /
  静态资源 / 敏感文件 / 安全回归包 / 导出面安全包 / 终局欠账包——任一红即不可发布
- 安全回归包覆盖：含 `\`/`@` 链接 400、跨源写请求 403、`/docs` 404、CSP/nosniff/DENY 头、
  EPUB 本地图片 containment（框外必拒 + 框内必嵌双向锁）、Cookie `0600`
- 发布门禁 `check_release.py` 四项：tag/版本四方一致、CHANGELOG 段落、**wheel 打包路径冲突静态检查**
  （v5.0.0 首发的 Windows 教训：测试走源码树测不到打包面，必须由门禁自己把关）

## 🤝 参与贡献

```bash
git clone https://github.com/xfengyin/zhihu-salt-novel-downloader
cd zhihu-salt-novel-downloader
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest tests          # 896 项，全离线
.venv/bin/python scripts/acceptance.py    # 11 项验收门禁，应 ALL GREEN
```

- 先读 [docs/ARCHITECTURE_SPEC.md](docs/ARCHITECTURE_SPEC.md)（接口契约的唯一事实源）再动内核
- 文案与实现必须一致：本项目用「双向禁词用例」锁死这类漂移，改了实现不改文案（或反之）会被测试拦下
- 漏网的推广块、解析失败的页面：连同链接开 Issue，比加配置开关更受欢迎

## 📚 文档

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) —— v5 实际架构、任务生命周期、状态文件布局、关键决策记录
- [docs/SUPPORT_MATRIX.md](docs/SUPPORT_MATRIX.md) —— URL 类型支持矩阵
- [docs/ARCHITECTURE_SPEC.md](docs/ARCHITECTURE_SPEC.md) —— 接口契约与铁律
- [docs/ROADMAP.md](docs/ROADMAP.md) —— v5.1 / v5.2+ 与「永不做」红线
- [CHANGELOG.md](CHANGELOG.md) —— 版本变更；GitHub Release 正文直接取对应段落

## License

[MIT](LICENSE) · 本项目仅供个人合法备份用途，与知乎无任何隶属关系。
