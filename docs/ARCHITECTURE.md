# v5 架构（实际形态）

> 状态：**v5.0.0-rc**。本文描述 v5 的真实分层与数据流，接口契约以
> [ARCHITECTURE_SPEC.md](ARCHITECTURE_SPEC.md) 为唯一事实源。内核各层（`engine` / `parse` / `export` / `shelf` / `auth`）、
> `app/server.py`、`app/static/`、`cli.py`、`update.py` 均已在树内并有离线测试；本文描述以规格书契约为准，
> RC 验收若发现偏差则回改本文（尤其 §3 生命周期与 §6 安全清单两节）。
> 旧全栈版（React 前端 / Tauri 桌面端 / NATS / OTel / SQLAlchemy / pluggy 插件层）已归档到 `legacy/fullstack` 分支，与本文件无关。

## 1. 一句话

一个 Python 包、一个进程、两个平级入口（CLI 与本地 Web），同步内核 + 线程池，运行时依赖恒为 5 个。

## 2. 分层

```text
入口层    cli.py        login / download / shelf / doctor / gui（裸启动 = gui）
          app/server.py FastAPI 工厂 create_app + SSE + /api/*（默认只监听 127.0.0.1）
          app/static/   原生 HTML/CSS/JS，零构建
            |  只经公共 API 调用，不复制业务逻辑
编排层    engine/       client.py    限速 / 签名注入 / 指数退避 / 线程安全（ZhihuClient）
                        fetcher.py   resolve_book / download_book / check_new_chapters
                        checkpoint.py 逐章断点（CheckpointStore，原子写）
            |
能力层    parse/        urltype 七类识别 → parser 结构化 → cleaner 清洗 → classifier 分类
          export/       txt / md / epub（精排：封面 + 两级 TOC + 稳定 identifier + 内嵌 CSS）
          shelf/        书架 JSON 纯存储层（绝不 import engine）
          auth/         cookies / qr / browser(可选) / doctor
            |
叶子层    signature.py（x-zse-96 / x-zst-81，纯标准库；固定向量回归钉死）
          types.py（共享 dataclass 契约）  errors.py（SaltError 异常树）
```

依赖方向严格向下，无回边：`engine` 可 import `parse`/`export`/`auth`；`parse`/`export`/`shelf`/`auth` 绝不 import `engine`。
追更的组合逻辑（`check_new_chapters` × `shelf.list()`）放在 CLI / server 层，因为 `shelf` 只是存储层。
`engine/fetcher.py` 对 `parse`/`export` 采用函数内延迟导入，因此单层未落地时整包仍可 import、测试可注入假模块。
跨层数据只有 `types.py` 的 dataclass（`Block`/`Article`/`ChapterRef`/`BookMeta`/`ProgressEvent`/`BookResult`/`ShelfBook`）；
跨层错误只有 `errors.py` 的子类，且面向用户的消息一律中文 + 含下一步动作。

## 3. 一次下载任务的完整生命周期

```text
用户贴链接
  |
  |  POST /api/download {url, format, resume}   （CLI：download 子命令 → 同一个 download_book）
  v
[校验] 闸门与 HTTP 栈同解析器（urllib3.util.parse_url）取主机名 + 硬拒反斜杠与 @，非知乎域一律 400
         （仿冒域 / userinfo 注入 / IP 直连 / 解析器差分载荷全拒）；请求发出后再对实际落点复校验一次
  v
[建任务] TaskStore 登记 Task（LRU 上限 50，只淘汰终态任务）→ 线程池 max_workers=2 领取；
         任务专属 client = base.copy_with(rate_limit=...)，各自独立 requests.Session（杜绝跨任务竞态）
  v
[resolve_book] urltype.detect(url)
     |- app_column/app_section -> UnsupportedUrlError（消息内嵌 story->market 替换示例）-> emit(error) -> 结束
     |- section/answer/zhuanlan -> fetch 该页 -> parse_article -> BookMeta(1 章，正文页已预取不重复请求)
     |     （fetcher._SINGLE_PAGE_TYPES 同一分支：单章节 / 公开回答 / 专栏文章一律按单篇下载，CLI 与 GUI 同义）
     |- column                 -> fetch 目录页 -> parse_toc -> BookMeta(N 章)（TOC 标题权威覆盖 og:title）
     |- unknown                -> UnsupportedUrlError
  v
emit ProgressEvent(kind=toc, total=N)            <- CLI 起进度条 / SSE 推给前端
  v
[续传] CheckpointStore.load() -> get_done_urls()，已完成章节直接跳过（计入 BookResult.skipped_existing）
  v
[并行取章] ThreadPoolExecutor(workers=3) x 剩余章节 —— 吞吐上限是 rate_limit（默认 2 请求/秒），
           workers 只让「在等的请求」互相重叠、解析/清洗与等待并行，不提高每秒请求数；每章：
     client.fetch(url)   内部：时间槽限速 -> signed_headers(x-zse-96) -> GET
                         -> 网络错误/429/5xx 指数退避重试 1/2/4s（emit retry）；403 立即抛不重试
       -> parse_article(html)  -> Block 列表 + Article.chapter_type（内部 classify：normal|extra|author_note；h2/h3/p/li/quote/img，懒加载 data-original 优先）
       -> cleaner.clean()      -> 整块过滤广告与水印（内置三组词表 + 库层 extra_patterns；无配置层，不砍短行）
       （fetcher 不直接 import classifier：分类随 parse_article 产出，column 路径以目录标注优先）
       -> checkpoint.put_chapter(url, article)   先写 .tmp 再 os.replace（正文缓存 + 状态）
       -> emit ProgressEvent(kind=chapter, current, total, title)
  v
[失败] 某章最终失败 -> 置 abort 标志中止整本 -> emit(error)：消息形如
       「第 N 章《…》下载失败：<中文原因>；已完成章节已保留，可续传」，并保留 .zhihu_state/ 供重跑续传；
       章节缓存缺失/损坏走自愈重取（R1-m1）；仅状态文件损坏才抛 CheckpointError 提示「删除该文件或加 --no-resume」
  v
[导出] 按目录顺序从 checkpoint 读回 Article 列表 -> export.export_book(title, articles, fmt, output_dir)
       emit(export) -> 写出 <safe_filename(书名)>.{txt|md|epub}
       epub：SVG 封面 + 封面页；两级 TOC（正文 / 附录，番外与作者说归附录）；
             identifier = sha1(title|首章 url) 稳定值；图片：resolve 框内必嵌、框外与 SVG/SVGZ 拒（A10 双钉）
  v
[收尾] 保留断点 state+bodies（R1-M4 裁决：同链接重跑秒级重导出、追更只抓新章；清理=--no-resume 或书架移除 prune）-> shelf.record_download(result, fmt, chapter_urls)
       emit(done, files) -> Task.files 登记 basename 白名单 -> SSE 补发 [DONE] 并关流
```

进度协议只有一份（`ProgressEvent`），CLI 与 Web 都是它的渲染器：前端 `EventSource(/api/tasks/{id}/events)`，断线或 12 秒看门狗内收不到可解析事件即降级为 2 秒轮询 `GET /api/tasks/{id}`；
CLI 进度条纯 stderr 写（形如 `\r [███░░] 47/120 (39%) 第47章：xxx`），不引第三方库。

## 4. 状态文件布局（规格 §3）

```text
~/.zhihu_downloader/
  cookies.json                    登录态；写入即 chmod 0600 + 原子写（POSIX）
  shelf.json                      {books: [ShelfBook.to_dict()...]}；损坏则备份 .bak 并重建空书架（不崩）
  output/                         GUI 默认输出目录（CLI 默认为当前目录下的 ./output）

<output_dir>/.zhihu_state/
  <sha1(book_key)[:16]>.json      单本状态：title / total / fmt / 已完成 URL 集合
  chapters/<sha1(url)[:16]>.json  单章正文缓存（Article.to_dict()），成功后保留供追更复用，书架移除时随 prune 清理
<output_dir>/.zhihu_tasks/<sha1(url)[:16]>/  仅 GUI：每任务独立工作目录（纵深隔离并发；成功后产物挪回输出根并清理，失败保留断点）
```

写入铁律（所有 JSON 通用）：先写同目录 `.tmp` 再 `os.replace`，进程被杀不会留下半截文件。**两种损坏只有一条要手工**：
状态文件损坏 → 抛 `CheckpointError`（消息给「删文件或 `--no-resume`」两条出路）；章节缓存缺失/损坏 → 自愈重取，不打扰用户（R1-m1）。
Windows 下状态目录同为 `%USERPROFILE%\.zhihu_downloader`：不写注册表、不装服务、不留后台进程，删目录即彻底卸载。

## 5. 决策记录

### ADR-1 同步内核 + 线程池，而不是 asyncio

- 背景：旧全栈版用 `asyncio + aiohttp`；v4 极简版退回同步 `requests`。两版都要解决「百章串行太慢」。
- 决策：I/O 保持同步 `requests`；并发用 `ThreadPoolExecutor`（任务级 2、章节级 `workers`）；
  限速与 session 访问由 `threading.Lock` 保护；进度用回调协议而非 async 流。
- 理由：① 真实瓶颈是**限速**（默认 2 请求/秒），不是并发度 —— 事件循环的吞吐优势拿不到；
  ② `x-zse-96` 签名是纯 CPU 同步计算，放进事件循环无收益；③ 测试铁律要求 mock 只在 `requests.Session` 边界，
  同步代码的离线断言直白，asyncio 需额外事件循环夹具（旧版 135 passed / 19 errors 正是这类耦合的账单）；
  ④ 「抗失效」的前提是可读可修：目标维护者是单人，任何要求双套 I/O 心智模型的设计都是负债。
- 代价与对策：**吞吐上限 = `rate_limit`，而不是线程数** —— `ZhihuClient` 用一把 `threading.Lock` 同时保护
  限速时间槽预约与 session 请求，多线程只能让「互相在等的请求」重叠（并行解析），每秒请求数不会超过设定值。
  这是有意的：那把锁就是产品承诺「平台友好」的实现方式，文档与文案不得把它宣传成「并发提速 N 倍」。
  想更快只能调 `--rate-limit`（doctor 会在 >5 请求/秒时 warn）；取消/超时不做细粒度（任务短，
  失败即整本中止 + 断点续传，语义更简单）。

### ADR-2 零构建 Web UI，而不是 React / Tauri

- 背景：旧全栈版含 4,184 行 React/TS + 496 行 Rust(Tauri)，旧 README 535/538 行在讲它；
  而发布数据显示主力用户是 Windows 非技术用户（EXE 下载 42 : Linux 6）。
- 决策：GUI = FastAPI 托管的 `app/static/`（原生 HTML/CSS/JS），禁止 Node 与打包器（规格 §0 铁律 2）。
- 理由：① 交付面只有一个产物 —— `pip install` 或单个 PyInstaller 二进制，不必再维护
  「先 npm build 再打二进制」这条最容易在 CI 与用户机器上断裂的链路（旧版的前端产物步骤正是永假死代码）；
  ② 体积与依赖面：省掉整套前端工具链，运行时依赖恒为 5 个；③ 源码即产物：用户和贡献者打开 `app.js`
  看到的就是正在跑的东西，符合「不黑箱」的信任定位；④ 界面本身很薄（一个表单 + 一条 SSE 进度 + 一个书架列表），
  SPA 框架收益为零；⑤ PyInstaller 打包静态目录只需 force-include，不需要处理前端资源的 hash 文件名。
- 代价与对策：无组件化 → 以 IIFE + `app.js` 顶部的 API 清单约束 DOM 契约；无热更新 → 静态页刷新即生效；
  SSE 兼容性 → 断线降级轮询；无 i18n 框架 → 中文硬编码，英文化列入 v5.2+。

## 6. 安全面收敛清单（发布前对抗审查 R2 之后）

- **网络出口**：默认只监听 `127.0.0.1`（非回环告警列出四条具体风险）· URL 闸门与 HTTP 栈同解析器且硬拒
  `\` / `@` · 跨域重定向不携带登录 Cookie（禁默认跟随 + 逐跳域校验 + Cookie 绑域）· 书架/追更的磁盘 URL 同样先过闸。
- **本地 API**：写接口校验 Origin/Referer 必须指向本机（跨站 403）· 关 `/docs` 与 openapi · 全站 CSP / `nosniff` /
  `X-Frame-Options: DENY` / `no-store` · 未终态任务超总量闸 429 · 任务表 LRU 50 · `/api/cookies` 只回布尔 · 文件下载只查登记的 basename 白名单。
- **落盘与导出**：Cookie 以 `O_CREAT|O_EXCL` + `0600` 原子创建（Windows 无 POSIX chmod 语义，doctor 如实降级为
  NTFS ACL 提示）· JSON 一律 `.tmp` + `os.replace` · Markdown 全字段转义 · EPUB 图片内嵌唯一判据 = containment（以输出目录为根
  resolve 后的 realpath 在框内；绝对/相对/../软链同一条边界，框外必拒、框内必嵌，正反双钉焊在 A10；SVG/SVGZ 永不内嵌）。
- **输入与提示**：扫码错误只带类型名、不回显远端 payload，token 强制格式校验 · 升级提示净化（控制字符剥离 + 长度上限
  + Releases 前缀白名单与 `urlsplit` 复核，入库与渲染各一次）· 限速 0.5~5 以 `doctor` 为单源（CLI 与 GUI 同界）· 版本单一来源由门禁强制。

> 刻意不做：多用户鉴权（本地单用户工具，暴露面靠只监听回环收敛）、遥测上报、代理池与账号轮换。
> 红线清单见 [ROADMAP.md](ROADMAP.md)「永不做」。
