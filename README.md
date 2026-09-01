# 知乎盐选小说下载器 v5

> **把你已购买的盐选小说，变成能舒服躺在 Kindle / Kobo / Boox 上的精排电子书** —— 双击即用、扫码登录、断点续传、追更增量。

[![CI](https://github.com/xfengyin/zhihu-salt-novel-downloader/actions/workflows/ci.yml/badge.svg)](https://github.com/xfengyin/zhihu-salt-novel-downloader/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/xfengyin/zhihu-salt-novel-downloader)](https://github.com/xfengyin/zhihu-salt-novel-downloader/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/xfengyin/zhihu-salt-novel-downloader/blob/master/LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)

> 状态：**v5.0.0-rc**。命令行接口按 [架构规格书 §2.15](docs/ARCHITECTURE_SPEC.md) 书写；内核各层（engine / parse /
> export / shelf / auth）、`app/server.py`、`cli.py`、`update.py` 均已在树内并有离线测试，**待 RC 验收**：
> 验收若发现与本文措辞不符，以规格书与代码为准并同步修订本文（本文不描述未实现的能力）。
> v5 起本仓库只有一条主线；旧版实现（含其桌面端与前端形态）按 `PUSH_GUIDE.md` 归档到 `legacy/fullstack` 分支，本文不再描述。

<!-- TODO: 真实截图（GUI 下载进度页 + 书架页），发布前补，勿用示意图 -->

---

## 30 秒上手（Windows，不需要装 Python）

1. 打开 [Releases](https://github.com/xfengyin/zhihu-salt-novel-downloader/releases)，下载 Windows 产物
   `zhihu-downloader-<版本>-windows-x64.exe`（若该版本文附带 zip，解压后取出其中的 EXE），放到任意文件夹。
2. **双击这个 EXE**：无参数启动等价于 `gui` —— 起本地服务，等服务就绪后自动打开浏览器，全程不用敲命令。
   首次运行被 Windows SmartScreen 拦住时，点「更多信息」→「仍要运行」（见[常见问题](#常见问题)）。
3. 页面里点「扫码登录」→ 用手机知乎 App 扫一扫 → 登录态自动保存到本机。
4. 把盐选链接粘贴进输入框，例如 `https://www.zhihu.com/market/paid_column/1234567890123456789`。
5. 格式选 `epub`（墨水屏推荐）→ 点「开始下载」→ 章节进度条走完后点「下载文件」。
6. 把 `.epub` 拷进阅读器（USB 拷贝或 Send-to-Kindle 邮箱）即可离线阅读。

Web 服务只监听本机 `127.0.0.1`，正文与 Cookie 只发给知乎本身（下载必需），**不向任何第三方上传内容**：
对外唯一的另一个请求，是启动时向 GitHub 查一次最新版 —— 固定地址、不带 Cookie / 书名 / 链接 / 用户标识
（UA 是一个写死的产品串），可用 `--no-update-check` 关掉。下载中途断网、关窗、断电都行：
重新粘贴同一条链接（CLI 则是重跑同一条命令）会继续下载未完成的章节（断点续传），不必从第 1 章重来。
本项目刻意**不与风控赛跑**：120 章的书在默认限速下至少要一分钟量级的请求时间（实际取决于页面响应），
这是「能长期用下去」的代价，不做多倍速抓取。

连载中的书下载后会自动进「我的书架」；作者更新了就在书架点「追更」，只下新增章节并重排整本。

## 功能一览（对齐实际能力）

| 能力 | 说明 |
|---|---|
| 扫码登录 | 知乎 App 扫码，Cookie 自动落盘（`0600` 权限），无需手工复制粘贴 |
| Cookie 导入 | 三种格式自动识别：JSON 对象 / Netscape `cookies.txt` / `k=v; k2=v2` 原始串 |
| 浏览器 Cookie（可选） | `pip install ".[browser]"` 后 `login --browser` 直接读 Chrome / Edge / Firefox 的知乎 Cookie |
| 断点续传 | 逐章落盘到 `<输出目录>/.zhihu_state/`；某章最终失败时中止整本、已完成章节全部保留，重跑同一条命令自动跳过续传（错误消息也会这么指引）；章节缓存损坏会自动重取该章（自愈），只有**状态文件**损坏时才需要删状态文件或加 `--no-resume` 重下整本 |
| 章节级进度 | CLI 进度条 + Web SSE：当前第几章 / 总数 / 章节标题，不用手动刷新 |
| 限速内并行 | 整体节奏由客户端限速钳制（默认 2 请求/秒，跨线程预约时间槽）；`--workers` 只让等待中的请求互相重叠、解析与清洗并行，**不提高每秒请求数** |
| 失败重试 | 网络错误与 429/5xx 指数退避重试 3 次（1/2/4 秒）；403 不重试，直接给可操作的中文提示 |
| 番外自动归类 | 分类器识别「正文 / 番外 / 作者说」，EPUB 把番外与作者说归入「附录」目录节点 |
| EPUB 精排 | 封面页 + 两级目录 + 稳定 identifier（对书名与首章链接取 sha1，多次导出可被阅读器合并为同一本书）+ 内嵌排版 CSS |
| MD / TXT 导出 | MD 保留 `h2`/`h3` 层级、列表、引用、图片引用；TXT 拍平为纯文本 |
| 书架 + 追更 | `~/.zhihu_downloader/shelf.json` 记录已下载章节，增量比对只下新章 |
| doctor 诊断 | Cookie 存在与权限、`z_c0` / `zse_ck` / `d_c0`、**签名自检**、限速合理性、网络探测、**断点缓存磁盘占用**（统计默认输出目录，超 500MB 给 prune 指引）；区分「Cookie 失效」与「签名轮换」两条排障路径 |
| 新版本提示 | doctor 与 GUI 启动时查 GitHub Releases 最新版（10 秒超时、失败静默），`--no-update-check` 可关闭 |
| 零构建 Web UI | 原生 HTML/CSS/JS，无 Node、无打包器；深浅色主题，SSE 断线自动降级为轮询 |

## 支持的链接

| 链接类型 | 示例 | 支持 | 说明 / 替代方案 |
|---|---|---|---|
| 盐选专栏（整本） | `https://www.zhihu.com/market/paid_column/1234567890123456789` | ✅ | 先抓目录再逐章下载，需要有效登录 Cookie |
| 盐选单章节 | `https://www.zhihu.com/market/paid_column/1234/section/5678` | ✅ | 只下该章；要整本请给专栏目录页链接 |
| 公开回答 | `https://www.zhihu.com/question/123456/answer/789012` | ✅ | 按单篇文章下载正文 |
| 知乎专栏文章 | `https://zhuanlan.zhihu.com/p/123456` | ✅ | 同上，`urltype.detect` 独立识别为 `zhuanlan` |
| 仅 APP 内阅读 | `https://story.zhihu.com/manuscript/paid_column/1234/5678` | ❌ | 需要知乎移动端私有 `mst`/`xsec` 设备签名，本项目**不会**去逆向（见下方红线）。**换成网页版链接就能下**，替换规则见下表后 |
| 非知乎链接 | `https://example.com/...` | ❌ | 只接受 `zhihu.com` 及其子域 |

**story 链接怎么换成网页版**（把 ID 照抄进模板即可，两条规则）：

- 整本：`story.zhihu.com/manuscript/paid_column/1234` → `www.zhihu.com/market/paid_column/1234`
- 单章：`story.zhihu.com/manuscript/paid_column/1234/5678` → `www.zhihu.com/market/paid_column/1234/section/5678`

嫌手工改麻烦就直接贴原链接：工具会报错并**把替换好的网页版链接整条打出来**（消息形如
「该链接（…）仅支持在知乎 APP 内阅读，无法直接下载。… 请改用网页版链接重试：…」），复制重贴即可。
前提是该内容网页端也可读且你已购；纯 APP 独占内容请直接在 App 内阅读。

逐条识别规则与状态见 [docs/SUPPORT_MATRIX.md](docs/SUPPORT_MATRIX.md)。

## 合规与使用限制

使用本工具前请仔细阅读以下限制：

- **仅下载已授权内容**：只可下载你本人已购买、已订阅或已获授权访问的盐选内容，仅用于个人离线备份。
- **不绕过付费墙**：本工具不破解、不绕过任何付费墙或权限校验；未购买 / 无权限的内容下载不到。
- **默认限速**：默认 2 请求/秒，合理区间 **0.5~5** 由 `doctor` 单源定义，命令行与图形界面共用同一区间、超界一律钳制
  （填 0 也不会「不限速」）。请勿为规避平台限制而无限调高。
- **禁止再分发**：禁止把下载内容用于传播、上传网盘或资源站、商业用途或任何侵犯版权的行为；请勿去除版权声明。
- **遵守服务条款**：请遵守[《知乎用户协议》](https://www.zhihu.com/terms)及相关法律法规（如《中华人民共和国著作权法》）。

> 使用即表示你同意以上限制；因违规使用产生的法律风险由使用者自行承担。

### 我们「永不做」（信任承诺）

以下是写进[路线图红线](docs/ROADMAP.md)的产品边界，任何版本都不会出现：

- ❌ 绕过付费墙 / 下载未购内容
- ❌ 逆向知乎 APP 端 `mst` / `xsec` 设备签名，抓「仅 APP 内阅读」内容
- ❌ 代理池 / 多账号轮换 / 任何对抗风控的能力
- ❌ 内置资源库、搜索盗版源、任何分发或营利功能
- ❌ 为了便于传播而抹除权利标识：清洗只针对平台自带的推广性脚标（`@知乎`、裸 `zhihu.com`、**块首独立**的
  `来源：` / `出处：` 短行、`相关推荐`），不是作者署名或版权段落；书名、作者、章节结构在 txt / md / epub 里都保留，
  正文句子中间的「出处：《某书》」也不会被删（规则锚定在块首）。拿本项目当「去水印工具」不在用途范围内。

### 为什么它「最抗失效」

盐选垂直工具最常见的死法，是知乎轮换一次 `x-zse-96` 签名就哑掉三个月。本项目的结构性答案：

1. `doctor` 做**本地签名自检**：用你的 `d_c0` 对固定 URL 生成 `x-zse-96` 并校验版本前缀，
   一句话告诉你是「Cookie 掉了（重新登录）」还是「签名算法过期了（升级工具）」，不用瞎猜、不用等报错；
2. 启动与 doctor 时自动检查 GitHub 新版本并给出下载链接；
3. v5.1 计划中的签名常量热补丁通道，把修复窗口从数天压到分钟级。

## 本地服务的边界

GUI 只是本机进程：默认监听 `127.0.0.1`，写接口校验请求来源（Origin/Referer 必须指向本机），
`/api/cookies` 只回布尔不回传 Cookie 值，导出文件按任务登记的白名单取用，全站响应带 CSP / `nosniff` /
`X-Frame-Options: DENY` / `no-store`。它**没有账号体系**，所以「谁能连到这个端口」就等于「谁能用你的登录态」：

- 用 `--host` 绑到非回环地址时，启动时打印的安全告警会**逐条列出四件事**，本文与它同口径：
  ① 用你的知乎账号发起下载（花你的配额、写你的硬盘）；② 下载你已导出的全部文件；③ 覆盖或清除你的登录 Cookie；
  ④ 借本工具访问你内网里的其它服务（路由器后台、云主机 metadata、只监听了本机的端口）。
  本服务**没有账号体系** —— 能连上这个端口的，就等同于本机使用者：来源校验只约束浏览器，不约束直接连端口的程序。
  只想本机用就别改 `--host`。
- 粘贴的链接里含 `@` 或反斜杠时会被直接拒绝（400 / 中文报错）。**这是保护，不是 bug**：这类写法是
  「闸门看到的域名」与「HTTP 栈真正连出去的主机」不一致的经典差分载荷（例如指向本机端口或内网地址），
  本项目让闸门与 HTTP 栈用同一个解析器并硬拒这类字符，代价就是它们永远进不了下载队列。

## 命令行速查

（接口契约见规格书 §2.15；安装方式见[开发者安装](#开发者安装)）

```bash
zhihu-downloader login [--browser]              # 扫码（终端打印二维码图片路径）；--browser 从浏览器导入
zhihu-downloader download --url U [-f txt|md|epub] [-o DIR] [--no-resume]
                              [--rate-limit R] [--workers N] [--batch-file F]
     # 想更快只能调 --rate-limit（不建议超过 5）；--workers 只重叠网络等待与并行解析，不提速
zhihu-downloader shelf [list|remove ID|update [--all]]    # 书架：列出 / 删除条目 / 追更
zhihu-downloader doctor [--no-network] [--cookie-file F]  # 诊断（Cookie 权限、签名自检、新版本提示）
zhihu-downloader gui [--host H] [--port P] [--no-browser] # 起本地服务并自动开浏览器（端口被占自动 +1 重试 3 次）
zhihu-downloader --version
```

裸启动（不给任何子命令）等价于 `gui`，这就是双击 EXE 即进图形界面的原因。

```bash
zhihu-downloader login                       # 1. 扫码登录
zhihu-downloader doctor                      # 2. 自检：缺 d_c0、权限过松都会直说
zhihu-downloader download --url "https://www.zhihu.com/market/paid_column/1234" -f epub -o ~/Books
zhihu-downloader shelf list                  # 3. 看书架
zhihu-downloader shelf update --all          # 4. 追更：只下新增章节
```

不写 `-o` 时，CLI 默认落在当前目录的 `./output/`，GUI 默认落在 `~/.zhihu_downloader/output/`；
`--rate-limit` 合理区间 0.5~5（超上限会被钳制，doctor 也会提示），`--workers` 默认 3、可钳到 1~8。

## 常见问题

- **报 HTTP 403 /「请求被知乎反爬拦截」怎么办？** 先跑 `zhihu-downloader doctor`，它会分流两种原因：
  Cookie 缺失或过期 → 重新 `login`；签名自检报 error → 算法与线上不匹配（不是你的 Cookie 问题），
  去 Releases 升级到最新版。403 不做无谓重试，但已完成章节留在断点里，修好后重跑同一条 `download` 命令即续传。
- **下到一半失败了，前面的白下了吗？** 没有。中止前已完成章节已写进 `<输出目录>/.zhihu_state/`，
  错误消息末尾也会告诉你「重新运行同一命令续传剩余章节」。章节正文缓存坏了不用管 —— 那一章会被自动重取
  （自愈）。只有两种情况才真需要重下整本：你手动加了 `--no-resume`，或 `.zhihu_state/` 里的**状态文件**损坏
  且你不愿手工删它（此时报错消息会直接把这两条出路写给你）。
- **能下公开回答或专栏文章吗？** 能。`question/.../answer/...` 与 `zhuanlan.zhihu.com/p/...` 按单篇文章处理，
  CLI 的 `download` 与 GUI 输入框都接受；只有「仅 APP 内阅读」的 `story.zhihu.com` 需要换成网页版链接（见上表）。
- **Windows 提示「已保护你的电脑」？** 本项目无代码签名证书，未签名的 PyInstaller 单文件包会被 SmartScreen 拦截：
  点「更多信息」→「仍要运行」。想更稳妥，可核对 Release 附件里的 `SHA256SUMS.txt`：
  `certutil -hashfile zhihu-downloader-<版本>-windows-x64.exe SHA256`。
- **macOS 提示「无法验证开发者」？** 右键点击二进制 →「打开」；或解除隔离属性：
  `xattr -d com.apple.quarantine ./zhihu-downloader-<版本>-macos-arm64`。
- **Cookie 存在哪里？权限对吗？** `~/.zhihu_downloader/cookies.json`：以 `O_CREAT|O_EXCL` + `0600` 原子创建
  （创建瞬间就是私有权限，没有「先落盘再 chmod」的窗口），再用 `os.replace` 换入。POSIX 下权限过松时
  doctor 会 warn 并给出 `chmod 600` 建议；Windows 无 POSIX chmod 语义，doctor 会如实降级为 info 提示
  （真实边界由 NTFS ACL 决定，别把该目录同步到 OneDrive 等共享位置）。退出登录：删掉该文件即可。
- **GUI 能被局域网其他设备访问吗？** 不建议。默认只监听 `127.0.0.1`；`--host` 给非回环地址时启动会打印安全告警，
  具体四条风险见[本地服务的边界](#本地服务的边界)。
- **为什么我粘的链接被说成非法？** 若链接里含 `@` 或反斜杠，那是闸门在拦 SSRF 差分载荷（见
  [本地服务的边界](#本地服务的边界)）；换成浏览器地址栏里复制出来的干净链接即可。
- **正文里夹着推广文字？** 清洗器按内置词表**整块**过滤平台推广脚标（广告/推广、`@知乎`、裸 `zhihu.com`、
  块首的 `来源：` / `出处：` 短行、`相关推荐`）；只有整块命中才删，不会因为「某行少于 3 字」误杀「好。」这类合法段落。
  边界要说清：`来源|出处` 只杀**块首且冒号后不超过 30 字**的独立脚标行，句中「这段引文的出处：《清史稿》」保留；
  代价是 `本文来源：…` 这种带前缀的脚标**按设计漏删** —— 删错正文比留个尾巴严重得多。想追加规则目前只能走库层
  参数 `clean(article, extra_patterns=["正则"])`：**界面与命令行都没有词表开关，v5 也刻意不做配置文件**；漏网的推广块
  请连同链接反馈到 Issues，我们更倾向改内置词表而不是加开关。

## 开发者安装

```bash
git clone https://github.com/xfengyin/zhihu-salt-novel-downloader
cd zhihu-salt-novel-downloader
pip install -e ".[dev]"              # 带 pytest / ruff / httpx
python -m pytest tests -q            # 全部离线：mock 只在 requests.Session 边界，零真实网络
zhihu-downloader gui --no-browser    # 冒烟：起服务但不自动开浏览器（默认 127.0.0.1:3000，被占自动 +1 重试 3 次）
zhihu-downloader doctor --no-network --no-update-check   # 冒烟：完全离线的自检
```

可选 `pip install -e ".[browser]"` 启用浏览器 Cookie 导入。运行时依赖只有 5 个：
`requests` / `beautifulsoup4` / `fastapi` / `uvicorn` / `ebooklib`，Python ≥ 3.10。

## 文档

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) —— v5 实际架构、任务生命周期、状态文件布局、关键决策记录
- [docs/SUPPORT_MATRIX.md](docs/SUPPORT_MATRIX.md) —— URL 类型支持矩阵（对齐 `parse/urltype.py`）
- [docs/ARCHITECTURE_SPEC.md](docs/ARCHITECTURE_SPEC.md) —— 团队接口契约（并行开发的唯一事实源）
- [docs/ROADMAP.md](docs/ROADMAP.md) —— v5.0 / v5.1 / v5.2+ 与「永不做」红线
- [CHANGELOG.md](CHANGELOG.md) —— 版本变更；GitHub Release 的说明正文直接取这里的对应段落

## License

[MIT](LICENSE)
