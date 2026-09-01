# v5 架构规格书（团队契约）

> 本文件是并行开发的唯一事实源。改接口必须先改本文件与 types.py。
> 包根：src/zhihu_downloader/。Python >= 3.10，类型标注完整，docstring 中文。
> 所有异常用 errors.py 层级；所有共享数据用 types.py dataclass。

## 0. 铁律
1. 运行时依赖只有 5 个：requests / beautifulsoup4 / fastapi / uvicorn / ebooklib。
   禁止新增运行时依赖（browser-cookie3 仅作为可选 extra，import 必须 try/except 降级）。
2. 零构建步骤：Web UI 是原生 HTML/CSS/JS，禁止引入 Node/打包器。
3. 全部测试离线：mock 只在 requests.Session 边界；禁止真实网络。
4. 版本号唯一来源 = src/zhihu_downloader/__init__.py:__version__（webapp/cli/pyproject 不得再写死；
   pyproject 的 version 由发布脚本校验一致）。
5. 用户可见错误消息一律中文、可操作（说下一步做什么）。
6. 文件写入原子性：JSON 状态文件先写 .tmp 再 os.replace。

## 1. 模块所有权与文件清单

| 模块 | 文件 | 负责 agent |
|---|---|---|
| 基础 | __init__.py __main__.py types.py errors.py signature.py pyproject.toml | ✅ 已完成（主审计人） |
| engine | engine/client.py engine/fetcher.py engine/checkpoint.py | E1 |
| auth | auth/cookies.py auth/qr.py auth/browser.py auth/doctor.py | E2 |
| parse | parse/urltype.py parse/parser.py parse/cleaner.py parse/classifier.py | E3 |
| export | export/base.py export/txt.py export/md.py export/epub.py | E4 |
| shelf | shelf/shelf.py | E5 |
| app | app/server.py | I1 |
| static UI | app/static/{index.html,app.js,style.css} | I2 |
| cli | cli.py | I3 |
| packaging | packaging/pyinstaller.spec .github/workflows/*.yml | P1 |
| docs | README.md CHANGELOG.md docs/ARCHITECTURE.md docs/SUPPORT_MATRIX.md | D1 |

每个包目录都要有 __init__.py（re-export 公共 API，见下）。

## 2. 公共 API 契约（精确签名）

### 2.1 engine/client.py —— ZhihuClient（线程安全）
```python
class ZhihuClient:
    def __init__(self, cookie_file: str | Path | None = None, timeout: float = 20.0,
                 rate_limit: float = 2.0, retries: int = 3) -> None
    # 行为：加载默认 cookie_file（auth.cookies.DEFAULT_COOKIE_FILE）如存在。
    # 线程安全：内部 threading.Lock 保护 (a) 限速计时 (b) session 请求。
    # 不原地改 self.rate_limit —— 提供 copy_with(rate_limit=...) -> ZhihuClient（共享 cookie 文件路径）。

    def get_cookies(self) -> dict[str, str]
    def save_cookies(self, cookie_file: str | Path | None = None) -> Path   # 委托 auth.cookies.save（0600）
    def load_cookies(self, source: str | Path | dict[str, str]) -> None      # 委托 auth.cookies.load
    def has_valid_signing_cookie(self) -> bool   # d_c0 in cookies
    def fetch(self, url: str) -> str
    # fetch：限速→签名→GET→重试（指数退避 1/2/4s，仅对网络错误与 429/5xx；403 不重试直接抛）。
    # 403 → ZhihuError("请求被知乎反爬拦截（HTTP 403），请重新登录或更新 Cookie 后重试")
    # 404 → ZhihuError；重试耗尽 → ZhihuError 含最后原因。
    def signed_headers(self, url: str) -> dict[str, str]  # 复用 signature.generate_zhihu_sign
# on_retry（E1 契约扩展，主审批准）：可选实例属性 on_retry(url, attempt, delay_sec, reason)；
#   fetcher 仅在客户端已声明时挂接并 finally 还原；未声明则无 retry 事件（降级行为）。
```
UA 常量更新为现代值（Chrome/124 on Windows NT 10.0），保留 zhihu-salt/<version> 后缀。

### 2.2 engine/checkpoint.py —— CheckpointStore
```python
class CheckpointStore:
    def __init__(self, state_dir: Path, book_key: str) -> None
    # 文件 = state_dir / f"{sha1(book_key)[:16]}.json"；state_dir 默认 output_dir/.zhihu_state
    def load(self) -> dict  # 不存在返回 {}；损坏抛 CheckpointError
    def save(self, data: dict) -> None  # 原子写
    def put_chapter(self, url: str, article: Article) -> None
    # 章节正文存 state_dir/chapters/<sha1(url)[:16]>.json（Article.to_dict()）
    def get_done_urls(self) -> set[str]
    def get_article(self, url: str) -> Article | None
    def set_meta(self, title: str, total: int, fmt: str) -> None
    def clear(self) -> None  # 删状态与章节缓存（--no-resume 前置清理 / prune 内部复用）
    def prune(self, book_key: str) -> None  # R1-M4 裁决新增：删单本 state+其 bodies，幂等
    def total_bytes(self) -> int  # doctor 报占用用（R1-M4 配套）
```

### 2.3 engine/fetcher.py —— 下载编排（核心）
```python
def resolve_book(client: ZhihuClient, url: str) -> BookMeta
# 1) parse.urltype.detect(url)：
#    - app_only → raise UnsupportedUrlError(含 story→market 替换建议)
#    - section → fetch 该页，parse.parser.parse_article → BookMeta(title=章标题, chapters=[1 章])
#    - column  → fetch 目录页，parse.parser.parse_toc → BookMeta(title, chapters=[...])
#    - unknown → raise UnsupportedUrlError
def download_book(client, url, fmt="md", output_dir=".",
                  progress: Callable[[ProgressEvent], None] | None = None,
                  resume: bool = True, workers: int = 3,
                  meta: BookMeta | None = None) -> BookResult
# meta（E1 契约扩展，主审批准）：上层先 resolve_book 得有序 ChapterRef 供 shelf 记账，
#   再传 meta 复用目录页结果，避免目录被抓两次。
# 流程：resolve_book → emit ProgressEvent("toc", total=n)
#   → 对未完成章节用 ThreadPoolExecutor(workers) 调 client.fetch + parse_article + cleaner.clean
#   → 每章完成：checkpoint.put_chapter + emit("chapter", current, total, title)
#   → 单章最终失败：emit("retry") 由 client 内部处理；仍失败则中止整本并 emit("error")，
#     但已完成章节保留在 checkpoint（下次 resume 续传）
#   → 全部完成：从 checkpoint 读回 Article 列表 → export.export_book → emit("export")→emit("done")
#   → resume=False 时先 checkpoint.clear()
# 返回 BookResult(title, url, chapters, files, skipped_existing)
def check_new_chapters(client, url, known_urls: list[str]) -> list[ChapterRef]
# resolve_book 后 diff 出未下载章节（保持目录顺序）
```

### 2.4 auth/cookies.py
```
DEFAULT_COOKIE_FILE = Path.home()/".zhihu_downloader"/"cookies.json"
def save(cookies: dict[str,str], path: Path | None = None) -> Path   # chmod 0600，原子写
def load(path_or_text) -> dict[str,str]  # JSON / Netscape(7列+ #HttpOnly_) / name=value 三种格式
def parse_cookie_string(text: str) -> dict[str,str]  # "k=v; k2=v2"
def logout(path=None) -> bool  # 删除文件
```
### 2.5 auth/qr.py —— 从 v4 client.py 抽出（login_qr_start/image/poll 三函数，接收 client 参数）
```python
def start(client) -> dict  # {"token","image_url"}
def image(client, token) -> bytes
def poll(client, token) -> dict  # {"status": waiting|scanned|confirmed|error|expired, "user_id", "error"}
# confirmed 时写 cookie（经 auth.cookies.save，0600）并更新 client.session
```
### 2.6 auth/browser.py —— 移植 src/auth/browser_cookie.py（Chrome/Firefox/Edge），
依赖 browser_cookie3（try import，缺失时 raise AuthError("未安装 browser-cookie3，请 pip install 'zhihu-salt-novel-downloader[browser]'")）。
### 2.7 auth/doctor.py
```python
def run_checks(cookie_file=None, rate_limit=None, network=True) -> list[tuple[str,str,str]]
# 检查项（level, name, msg）：版本 / Python / Cookie 存在 / z_c0 / zse_ck / d_c0(签名必需!) /
# 签名自检（用 d_c0 对固定 URL 生成 x-zse-96，验证前缀 "2.0_"，区分"Cookie 缺失"与"签名失效"）/
# 限速合理性 / 网络探测（可选）
```

### 2.8 parse/urltype.py —— 移植旧版 detect_url_type
```python
def detect(url: str) -> str  # "answer"|"column"|"section"|"app_column"|"app_section"|"zhuanlan"|"unknown"
def is_app_only(url: str) -> bool
def friendly_hint(url_type: str) -> str  # 中文提示；app_only 给出 story→market 替换法
```
### 2.9 parse/parser.py —— 结构化解析（v5 关键升级）
```python
def parse_article(html: str, url: str = "") -> Article
# 选择器降级链同 v4（RichText/Post-RichTextContainer/RichContent-inner/article/Post-RichText）
# 遍历容器内 p/h2/h3/li/blockquote/img → Block 列表（img 保留 src/alt；懒加载 data-original 优先）
# 标题：og:title > h1.Post-Title > h1 > title；找不到 raise ParseError
def parse_toc(html: str, base_url: str) -> list[ChapterRef]  # v4 parse_section_links 升级：同时抓标题文本
def parse_page_title(html: str) -> str
```
### 2.10 parse/cleaner.py —— 移植旧版 ContentCleaner（广告/水印正则表，可传自定义 patterns）
```python
def clean(article: Article, extra_patterns: list[str] | None = None) -> Article  # 就地过滤 Block
```
### 2.11 parse/classifier.py —— 移植旧版：classify(title: str) -> str ("normal"|"extra"|"author_note")
### 2.12 export/ —— 统一入口
```python
# export/base.py
def safe_filename(name: str, max_len: int = 80) -> str  # 同 v4
def resolve_output_dir(output_dir) -> Path
# export/__init__.py
FORMATS = ("txt", "md", "epub")
def export_book(title: str, articles: list[Article], fmt: str, output_dir) -> list[str]
# txt/md/epub 各自模块实现 export(title, articles, output_dir) -> str(path)
# md：h2/h3 保留层级、li→-、quote→>、img→![](src)
# epub：封面页（书名大字+生成图）、TOC 两级（卷=章、番外归入"附录"）、图片内嵌（下载失败降级为 alt 文本）、
#       图片信任规则（R2#5 → A10 门禁冻结）：containment 唯一判据——src 以 output_dir 为根 resolve
#       （绝对/相对/../软链同判据）后必须落在框内；框外拒绝、SVG/SVGZ 拒绝；正反两钉在 scripts/acceptance.py A10；
#       identifier = sha1(f"{title}|{articles[0].url}") 稳定值、内嵌基础 CSS（段首缩进、行距 1.6）
```
### 2.13 shelf/shelf.py
```python
DEFAULT_SHELF_FILE = Path.home()/".zhihu_downloader"/"shelf.json"
class Shelf:
    def __init__(self, path: Path | None = None)
    def add_or_update(self, book: ShelfBook) -> None
    def remove(self, book_id: str) -> bool
    def list(self) -> list[ShelfBook]
    def get(self, book_id_or_url: str) -> ShelfBook | None
    def record_download(self, result: BookResult, fmt: str) -> ShelfBook  # 由 fetcher 成功后调用
# 注意：shelf 是纯存储层，不 import engine；追更组合逻辑（check_new_chapters × shelf.list）在 CLI/server 层完成。
# 标准记账通路（E1 追加轮定稿）：meta = resolve_book(client, url) → download_book(..., meta=meta)
#   → shelf.record_download(result, fmt, chapter_urls=[ch.url for ch in meta.chapters])
```
### 2.14 app/server.py —— create_app(client=None) -> FastAPI
```
GET  /api/health            -> {ok, version}
GET  /api/cookies           -> {has_cookie, z_c0, zse_ck, d_c0}（布尔，不回传值！）
POST /api/qrcode            -> {token, image_url}
GET  /api/qrcode/{t}/image  -> image/jpeg
GET  /api/qrcode/{t}/status -> qr.poll 结果
POST /api/cookies/import    -> {raw: str} 解析并保存（0600）
DELETE /api/cookies         -> 登出
POST /api/download          -> {url, format, resume?} → {task_id}
   ⚠️ 服务端校验：urlparse(url).hostname 必须 endswith zhihu.com，否则 400（SSRF 防护）
GET  /api/tasks             -> 摘要列表（LRU 上限 50，超出淘汰最旧已完成）
GET  /api/tasks/{id}        -> 详情含 progress {current,total,title}
GET  /api/tasks/{id}/events -> SSE（text/event-stream），事件=ProgressEvent.to_dict()，done/error 后关闭
GET  /api/files/{task_id}/{filename} -> FileResponse（filename 过 safe_filename 校验防穿越）
GET  /api/shelf             -> Shelf.list()
POST /api/shelf/{id}/update -> 追更：下载新章 → 重导出整本 → 更新条目
DELETE /api/shelf/{id}      -> 移除条目（不删文件）
GET  /                      -> 静态 UI
```
安全：默认 host=127.0.0.1；--host 非回环时启动打印 ⚠️ 告警；每个任务独立 ZhihuClient 实例（不共享 session）；
下载线程用 ThreadPoolExecutor(max_workers=2) 且任务内串行取章节（并发由 fetcher workers 控制）。
### 2.15 cli.py —— argparse 子命令
```
zhihu-downloader login [--browser]        # 扫码（终端打印二维码路径）或浏览器导入
zhihu-downloader download --url U [-f txt|md|epub] [-o DIR] [--no-resume] [--rate-limit R] [--workers N] [--batch-file F]
zhihu-downloader shelf [list|remove ID|update [--all]]
zhihu-downloader doctor [--no-network] [--cookie-file F]
zhihu-downloader gui [--host H] [--port P] [--no-browser]   # 起服务+自动开浏览器（webbrowser.open）
zhihu-downloader --version
```
download 显示进度条：\r [███░░] 47/120 (39%) 第47章：xxx （纯 stderr 写，无第三方库）。
Windows UTF-8 兜底保留 v4 cli.py:224-231 写法。
**双击即用（产品级决策，市场调研驱动）**：无任何参数的 `zhihu-downloader` 等价于 `gui`（起服务+自动开浏览器），
Windows 用户双击 EXE 即进入图形界面；已显式给子命令时不触发。gui 端口被占时自动 +1 重试 3 次并在浏览器打开实际端口。

### 2.16 抗失效通道（市场调研驱动的产品级差异点）
```python
# update.py（I3 拥有）
def check_tool_update(current: str) -> dict | None
# GET https://api.github.com/repos/xfengyin/zhihu-salt-novel-downloader/releases/latest（10s 超时，失败静默）
# 返回 {"latest": "v5.1.0", "url": "...", "has_update": bool}；CLI doctor 与 gui 启动时调用（可 --no-update-check 关闭）
# 意义：竞品普遍"失效即死"，本产品把"当天可修复"变成产品承诺（痛点#1 的结构性答案）
```
签名常量热补丁通道（远程 JSON 覆盖 signature 常量）列入 v5.1（见 docs/ROADMAP.md），v5.0 不做——数据面攻击面需要单独设计。

## 3. 数据与状态布局（用户机器）
```
~/.zhihu_downloader/
├── cookies.json      # 0600
├── shelf.json        # {"books": [ShelfBook.to_dict()...]}
└── output/           # gui 默认输出目录
<output_dir>/.zhihu_state/   # 断点：<key>.json + chapters/<sha1>.json（成功后清理）
```

## 4. 测试矩阵（tests/，全部离线）
- test_client.py：限速/重试退避（mock time.sleep）/403 不重试/签名注入/线程安全冒烟（8 线程 fetch）
- test_checkpoint.py：原子写/损坏恢复/续传跳过
- test_fetcher.py：section/column 全链路（mock fetch 返回 fixture HTML）/进度事件序列/断点续传/追更 diff
- test_cookies.py：三种格式解析/0600/logout
- test_qr.py：五状态分支
- test_doctor.py：d_c0 缺失告警/签名自检分支
- test_urltype.py：7 种 URL 分类 + app_only 提示
- test_parser.py：结构保留（h2/li/img data-original）/无正文报错
- test_cleaner.py / test_classifier.py
- test_export.py：txt/md 结构/epub 可读（ebooklib 读回）/identifier 稳定/文件名安全
- test_shelf.py：增删改查/find_updates
- test_server.py：TestClient 全端点 + SSRF 400 + SSE 事件流 + 文件穿越防护
- test_cli.py：参数钳制/分发/--version 单源
- test_signature_vectors.py：固定向量回归（从当前实现生成一次并钉死）

## 5. 集成顺序
E1-E5 并行（互不 import 对方新代码，只依赖 types/errors/signature + 本规格签名）
→ 主审计人跑全量 pytest 修缝 → I1/I2/I3 并行 → P1/D1 并行 → 对抗审查 → 验收

## 6. 主审裁决记录（并行开发中的契约演进）
| 上报 | 裁决 | 落点 |
|---|---|---|
| E2#1 cookies JSON 数组退化成行解析垃圾键 | ✅ 缺陷，主审已修（startswith(("{","[")) 统一拒绝非对象），E2 钉桩测试同步更新 | cookies.py |
| E2#2 d_c0 分级：未登录 warn / 已登录缺 d_c0 error | ✅ 批准（优于规格原文，CLI 退出码能抓致命问题） | doctor |
| E2#3 doctor 新增"Cookie 权限"检查（0644→warn+chmod 提示） | ✅ 批准保留（安全承诺的一部分） | doctor |
| E2#4 qr.poll 返回值超集（raw_status/saved_to） | ✅ 批准；server 层按需 pick 三键 | qr |
| E2#5 qr 直接经 cookies.save 落盘（0600） | ✅ 批准（v4 save_cookies 不设权限正是审计缺陷） | qr |
| E2#6 browser 全空抛 AuthError 而非返回 {} | ✅ 批准（CLI 中文下一步提示优先） | browser |
| E2#7 越界自建 test_browser.py | ✅ 批准（自审模块零覆盖不可接受） | tests |
| E3#1 parse_article/parse_toc 顺手填 chapter_type/type | ✅ 批准（types.py 注释本就要求） | parse |
| E3#2 parse_toc 空目录返回 []，抛错权在 resolve_book | ✅ 批准（E1 已按此实现） | fetcher |
| E3#4 cleaner 整块过滤、不移植 <3 字短行规则 | ✅ 批准（防误杀「好。」类合法段落，v4 审计痛点） | cleaner |
| E5#1 record_download 扩展 chapter_urls 参数 | ✅ 批准（已写入 §2.13 调用方约定） | shelf |
| E1 修复：TOC 标题权威覆盖 og:title；UnsupportedUrlError 嵌具体替换 URL | ✅ 验收测试 test_e2e 6/6 绿 | fetcher |
| P1：editable 失败退回 PYTHONPATH=src 防假绿 | ✅ 批准 | ci.yml |
| E1#1-9 全部批准：单篇特判/on_retry 钩子/copy_with 超集/单章 1 请求/TOC 权威/market_replacement 暂居 fetcher/CheckpointError 映射下发 I1、I3/并发语义钉死（吞吐=限速，禁宣提速）/e2e cwd 泄漏主审已修 | ✅ | engine |
| E4#1 图片无下载归属、EPUB 内嵌恒走 alt 降级 | ✅ 裁决：v5.0 接受降级（盐选以文字为主），「章节图片下载+回填」列入 v5.1 | 全链路 |
| E4#2 plain_text 松散列表 | ✅ v5.0 接受（txt 从简） | types.py |
| E4#3 ebooklib 读回限制（get_content 重建 head、包内目录名 EPUB/） | ✅ 记录为团队知识 | tests |
| E4#4 SVG 封面避免引入 Pillow | ✅ 批准（封面页 XHTML 文本双保险） | epub |
| E1 计数更正：95 例（33+24+38）+ e2e 6 例；TOC 标题覆盖排除 URL 兜底伪标题 | ✅ 记录 | engine |
| I1 整改：meta= 复用（普通下载+追更目录页均只抓 1 次，53 测）；根因表述更正为「引擎已修+server 纵深防御」 | ✅ 验收 | app |
| pydantic 直接 import（server.py 请求体 BaseModel） | ✅ 裁决：fastapi 硬传递依赖、零新增安装重量，入依赖白名单（acceptance.py A4 同步） | app |
| I1 结项：meta= 复用（目录页 1 次抓取）、CheckpointError→「或关闭续传重试」映射、53 测 | ✅ 验收 | app |
| I2 契约模糊处 12 条选择（rate_limit 超集+422 回退/basename 下载/SSE 对账式收尾/状态归一化 isFinal/书架文件只读 chip/30s 安全同步） | ✅ 全部批准；shelf 文件端点入 v5.1（防穿越需独立设计） | static |
| 主审 Windows 审计：safe_filename 补 NTFS 保留设备名守卫（CON/NUL/COM1-9/LPT1-9 加下划线前缀，守卫置于截断后）+10 断言 | ✅ 已落地 | export/base.py |
| R2-P0-1 跨域 302 不剥 Cookie（z_c0 可送任意主机） | 🔴 S1 修复：allow_redirects=False+逐跳知乎域校验+Cookie 绑域 | client |
| R2-P0-2 SSRF 反斜杠+@ 解析器差分绕过（闸门 urlparse vs 栈 urllib3） | 🔴 S1：闸门改 urllib3 同解析器+硬拒 \ 与 @+response.url 复校验+错误消息去内网细节 | server/client |
| R2-P0-3 零鉴权+零 Origin（无 body form POST 可 CSRF 追更/扫码） | 🟠 S1：写接口 Origin/Referer 回环校验+关 docs+CSP/nosniff/DENY/no-store+未终态 429 | server |
| R2-#4 远端正文零净化进 .md（默认格式，本地预览 XSS） | 🟠 S2：html_escape+反引号转义+去 HTML 注释书名 | md |
| R2-#5 远端 img src 指向本机文件 → 读进 EPUB | 🟡 containment 唯一判据，**冻结于 A10 门禁**（框外必拒+框内必嵌双钉；翻转即 FAIL） | epub |
| R2-#6 追更通道缺 SSRF 复校验 | 🟡 S1 增补：shelf_update 显式过闸+fmt 校验 | server |
| R2-#7 qr 错误消息 repr 远端 payload（Cookie 可回显） | 🟡 S2：只带类型名+poll 规范化+token 正则 | qr |
| R2-#8 cookies.save 0600 竞态窗口+Windows 语义 | 🟢 S2：O_EXCL 0600 原子创建+doctor win32 如实降级 info | cookies/doctor |
| R2-#9 update.py int 上限异常+OSC 转义注入 | 🟢 I3 收尾修：token 限长+控制字符剥离+html_url 前缀白名单 | update |
| R2-#10 gui 端口 TOCTOU+盲睡开浏览器 | 🟢 I3 收尾修：health 就绪轮询再开 | cli |
| R2 排除项（14 种穿越变体/Cookie 值 API 泄漏/CORS 配置/EPUB 注入/qrcode CRLF 头注入/自动更新执行面） | ✅ 实测 NOT-AN-ISSUE，勿重复排查 | — |