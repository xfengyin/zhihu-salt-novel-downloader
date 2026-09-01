# 变更日志（Changelog）

本文件遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

GitHub Release 的说明正文由 CI 从本文件抽取对应版本段落生成，所以**段落标题必须形如 `## 5.0.0 - 2026-09-01`**
（`scripts/check_release.py` 在发布前会校验它存在且非空）。

## 5.0.0 - 2026-09-01

> v5 重构版：从「企业级全栈 + 极简双主线」收敛为**一个单文件应用**（CLI 内核 + 本地 Web UI）。
> 面向「把已购盐选小说备份到墨水屏」这一件事重做，主打双击即用与「最抗失效」。
> 本版为 v5.0.0-rc 阶段：内核各层、`app/server.py`、`cli.py`、`update.py` 均已在树内并带离线测试，
> 待 RC 验收；验收若与本文措辞不符，以规格书与代码为准并回改本文。

### Added

- **断点续传**（`engine/checkpoint.py`）：逐章落盘到 `<输出目录>/.zhihu_state/`（状态文件 + 章节正文缓存），
  单章最终失败时中止整本、已完成章节原样保留，重跑同一链接（或同一条命令）自动跳过续传，错误消息本身
  就写着「重新运行同一命令续传剩余章节」；**整本成功后缓存同样保留**——同链接重跑秒级重导出、书架追更只抓
  新增章节（清理入口：`--no-resume` 强制重下、书架移除时 prune 该本缓存）；
  全部 JSON 写入均为 `.tmp` + `os.replace` 原子写；
  章节正文缓存缺失或损坏一律**自愈**：`get_done_urls()` 把「文件在但解析不出」的章节排除在完成集合外，续传时现场
  重取并回填，不会拖到导出阶段才报错、更不逼用户走 `--no-resume`；只有**状态文件**损坏才抛 `CheckpointError`，
  中文提示「删除该文件或加 `--no-resume` 重新下载整本」。
- **章节级进度协议**（`types.ProgressEvent`）：`toc → chapter × N → export → done`（失败为 `error`），
  CLI 进度条与 Web SSE（`GET /api/tasks/{id}/events`）共用同一事件流；SSE 断线时前端自动降级为 2 秒轮询。
- **扫码登录**（`auth/qr.py`）：终端与 Web 双通道，`confirmed` 后经 `auth.cookies.save` 落盘并设权限 `0600`。
- **Cookie 三格式导入**（`auth/cookies.py`）：JSON 对象 / Netscape `cookies.txt`（含 `#HttpOnly_` 前缀）/ `k=v; k2=v2` 原始串自动识别。
- **浏览器 Cookie 导入**（`auth/browser.py`，可选 extra `.[browser]`）：Chrome / Edge / Firefox；未装 `browser-cookie3` 时给出中文安装提示。
- **doctor 诊断**（`auth/doctor.py`）：版本 / Python / Cookie 存在与权限 / `z_c0` / `zse_ck` / **`d_c0`** /
  **签名自检**（本地用 `d_c0` 生成 `x-zse-96` 并校验 `2.0_` 前缀，把「Cookie 失效」与「签名轮换」分流成两条排障路径）/
  限速合理性 / 网络探测 / **断点缓存磁盘占用**（`CheckpointStore.total_bytes` 汇总**默认输出目录**下的 `.zhihu_state`，
  超 500MB 给「书架移除不再追更的书」的 prune 指引；纯观测项，info 级不影响退出码）；`error` 级检查项决定 CLI 退出码。
- **新版本提示**（`update.py`，规格 §2.16）：doctor 与 GUI 启动时查 GitHub Releases 最新版
  （10 秒超时、任何异常静默返回；固定 https 常量地址，请求不带 Cookie / 书名 / 链接 / 用户标识，
  只有一个写死的产品 UA），`--no-update-check` 可关闭。
- **结构化解析**（`parse/parser.py`）：正文保留 `h2`/`h3`/`p`/`li`/`quote`/`img` 块级结构，图片懒加载 `data-original` 优先。
- **章节分类与清洗**（`parse/classifier.py`、`parse/cleaner.py`）：自动识别「正文 / 番外 / 作者说」；广告与水印按内置
  三组词表（`AD_PATTERNS` / `WATERMARK_PATTERNS` / `TRASH_PATTERNS`）整块过滤，库层可经 `extra_patterns` 追加正则；
  v5 不做配置文件，故 CLI / GUI 无词表开关（引擎侧目前也不传该参数，留作库层扩展点）。`来源：/出处：` 两条锚定为
  「块首 + 冒号后 ≤30 字」的独立脚标行：原无锚定 `search` 会连带删掉句中写了出处的正文段，现改为宁漏不误杀
  （`本文来源：…` 带前缀形态按设计保留）。
- **URL 类型识别**（`parse/urltype.py`）：七类识别（`answer`/`column`/`section`/`app_column`/`app_section`/`zhuanlan`/`unknown`），
  公开回答与专栏文章由 `fetcher._SINGLE_PAGE_TYPES` 按单篇下载，CLI 与 GUI 同义；
  `story.zhihu.com` 给出具体替换示例而非静默失败。
- **EPUB 精排**（`export/epub.py`）：程序生成 SVG 封面 + 封面页、两级目录（正文章 / 附录归集番外与作者说）、
  图片内嵌只看 resolve 后是否落在输出目录框内（框内必嵌、框外与 SVG/SVGZ 拒，正反双钉在 A10）、内嵌 CSS（段首缩进、行距 1.6）。
- **书架与追更**（`shelf/shelf.py`）：`~/.zhihu_downloader/shelf.json` 持久化已下载章节清单；
  `shelf update [--all]` / `POST /api/shelf/{id}/update` 只下新增章节并重排整本。
- **限速内并行**（`engine/client.py` + `engine/fetcher.py`）：客户端用一把锁做跨线程时间槽预约，吞吐上限就是
  `rate_limit`（默认 2 请求/秒）—— 这是「平台友好」的实现方式；`--workers` 只用于重叠网络等待与并行解析，
  不提高每秒请求数；网络错误与 429/5xx 指数退避重试 3 次（1/2/4 秒），403 立即抛出不做加重风控的重试。
- **本地 Web UI**（`app/static/`）：原生 HTML/CSS/JS 零构建；登录态胶囊、扫码、粘贴链接、格式选择、
  章节进度、任务列表、书架、文件下载、任务失败重试入口。
- **批量下载**：`download --batch-file F` 逐行读链接。
- **发布链路**：单 tag → `scripts/check_release.py` 门禁（tag / `__version__` / pyproject / CHANGELOG 四方一致）→
  全量 pytest → Win / Linux(ubuntu-22.04) / macOS(arm64) 三平台 PyInstaller 产物 + `SHA256SUMS.txt` → 聚合 Release。
- **离线测试矩阵**（`tests/`，15 个测试文件）：mock 只在 `requests.Session` 边界，零真实网络，
  含 `x-zse-96` 签名固定向量回归（一次生成、长期钉死，防签名实现被无声改坏）。

### Changed

针对 v4 审计确认的顽疾逐条修复：

- **断点续传缺失**（v4：100 章下到第 87 章失败即整本重来）→ v5 逐章落盘 + `resume` 默认开启，失败章节保留断点。
- **Web 任务竞态**（v4：4 个 worker 共享同一个 `requests.Session`）→ v5 每个任务用 `copy_with()` 派生独立
  `ZhihuClient`（各自持有 session），任务表 `LRU`（上限 50）+ 显式锁；下载线程池 `max_workers=2`，章节级并发交给 fetcher。
- **EPUB identifier 漂移**（v4：`abs(hash())` 随进程哈希随机化变化，同一本书每次导出都被阅读器当成新书）→
  v5 改为 `sha1(f"{书名}|{首章 url}")`，跨进程稳定。
- **doctor 盲区**（v4：查 `z_c0`/`zse_ck` 却不查签名真正依赖的 `d_c0`）→ v5 分级检查：未登录时 `d_c0` 缺失 warn，
  已登录却缺失判 error（此时下载必然 403），并新增签名自检与 Cookie 文件权限检查。
- **SSRF 与局域网暴露面**（v4：API 零鉴权零 URL 校验，`--host 0.0.0.0` 即把登录态交给局域网）→
  v5 服务端强制校验 `urlparse(url).hostname` 必须是 `zhihu.com` 或其子域（仿冒域 / userinfo 注入 / IP 直连一律 400），
  默认只监听 `127.0.0.1`，绑定非回环时启动打印告警；`/api/cookies` 只回布尔不回传 Cookie 值；
  `/api/files/{task_id}/{filename}` 走任务登记的文件名白名单精确查表，不拼接用户路径。
- **版本号 6 处漂移**（v4：发布物与代码对不上号）→ v5 唯一来源 `src/zhihu_downloader/__init__.py:__version__`，
  CLI / Web / PyInstaller 产物名 / pyproject 全部派生，并由发布门禁强制一致。
- **导出结构丢失**（v4：Markdown 把标题拍平、EPUB 无封面/无 TOC 层级/无图片）→ v5 导出层按 `Block` 类型逐一映射，保留层级。
- **请求 UA 过时**（v4：Chrome/86，2020 年）→ v5 更新为 Chrome/124 并保留 `zhihu-salt/<version>` 产品后缀。
- **清洗误杀**（v4：短于行宽的内容被当广告删掉）→ v5 只做整块过滤，不移植「少于 3 字短行」规则，避免误删「好。」类合法段落。
- **异常消息全部中文化且可操作**：所有面向用户的错误说明「下一步做什么」（如 403 提示重新登录或更新 Cookie）。
- **发布承诺与流水线一致**（v4：README 承诺 5 平台包，CI 实际各发 2 包且 Tauri 步骤是永假死代码）→
  v5 只有一条发布通道，产物清单与 README 逐字对齐；Linux 构建钉 `ubuntu-22.04`（glibc 2.35），
  修掉 v4 产物在 Debian 12 上不可运行的 glibc≥2.38 地板问题。
- **CI 加测试门禁**（v4：发布流水线零测试）→ 预检与全量 pytest 不过就不出包；`pip install -e` 失败退回 `PYTHONPATH=src` 防假绿。

### 安全加固（发布前对抗审查驱动）

第二轮对抗审查（R2）提出的各项按面归并收口，逐条裁决与落点见规格书 §6 表，此处不重复细节：
- **请求面**：跨域重定向不再携带登录 Cookie（禁默认跟随 + 逐跳知乎域校验 + Cookie 绑域注入）；下载闸门与真正
  发请求的 HTTP 栈同解析器，反斜杠 / `@` 一类解析器差分 SSRF 载荷一律 400，落点复校验兜底。
- **本地服务面**：写接口校验请求来源（Origin/Referer 必须指向本机，跨站 403）；关闭 `/docs` 与 openapi；全站补
  CSP / `nosniff` / `X-Frame-Options: DENY` / `no-store`；未终态任务超总量闸直接 429。
- **导出面**：Markdown 导出全字段转义（远端正文与书名不再逃逸结构，本地预览不构成 XSS）；EPUB 图片内嵌唯一判据收敛为
  containment：以输出目录为根 resolve 后的 realpath 必须落在框内 —— 绝对 / 相对 / `../` / 符号链接走同一条边界检查，
  框外必拒、框内必嵌（正反双钉焊在 `scripts/acceptance.py` A10）；SVG/SVGZ 拒绝内嵌，`~` 不做 expanduser。
- **凭据与输入面**：扫码失败只报类型名、不回显远端 payload，token 强制格式校验；Cookie 以 `O_CREAT|O_EXCL` 0600
  原子创建（Windows 无 POSIX chmod 语义，doctor 如实降级为 NTFS ACL 提示）；书架与追更的 URL 入口统一过同一道闸；
  升级提示把远端版本号与链接按外部输入处理：文本剥 C0/DEL/C1 控制字符并截 200 字符（`sanitize_console_text`），链接除
  前缀白名单外还过 `urlsplit` 复核 scheme / host / port / path（`https://github.com@evil.com/...` 这类 userinfo 差分即失效），
  且含任一控制字符时**整条丢弃而非洗成可用形态**；净化在入库与渲染两处各做一次（`update.py`，全部离线测试覆盖）。

### Removed

- 删除旧全栈实现的全部过度工程层（以下均为旧仓库中的文件与依赖，本仓库不再存在）：插件化 SPI（pluggy）、
  多用户 JWT 鉴权与默认硬编码密钥、SQLAlchemy 数据库层、NATS 消息总线、OpenTelemetry 链路追踪、
  异步 `asyncio + aiohttp` 内核、React/TypeScript/Tailwind Web 前端（`web/`）、Tauri 2 + Rust 桌面端、
  Docker 构建脚本、`config.yaml` 配置层、`docs/openapi/v3.yaml`（系他方 "TRAE API" 文档误拷）。
- 移除 v4「双主线」（旧仓库里全栈 `src/` 与极简 `simple/` 并行维护、用户不知道该用哪个）：v5 只有一条主线。
- 移除 v3/v4 的 tag 前缀互斥路由（`v*` 与 `v4*` 两条 workflow 各发一半产物）与 `build-desktop.sh` / `build_windows.bat` /
  `build_linux.sh` 等手写构建脚本（含未引号导致 `pyinstaller>=6.0.0` 被 shell 当重定向的缺陷）。
- 移除 mobi 导出（v4 声称支持但转换链质量无保障）：改走本机 Calibre `ebook-convert`，列入 v5.1。
- 被删代码不物理销毁：按 `PUSH_GUIDE.md` 的合并步骤整体归档到旧仓库的 `legacy/fullstack` 分支，
  提交历史与可回滚路径完整保留（该分支由维护者在合并时创建）。

## 4.3.0 及更早

v4 极简版与旧全栈版的记录随 `legacy/fullstack` 分支归档，不在本文件继续维护。
升级建议：v4 → v5 属**架构替换**而非增量升级，命令行入口与配置有变化，请按 README「30 秒上手」重新登录一次。
