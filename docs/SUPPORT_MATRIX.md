# 支持矩阵（URL 类型 × 支持状态）

> 状态：**v5.0.0-rc**。本表逐条对齐源码 [`src/zhihu_downloader/parse/urltype.py`](../src/zhihu_downloader/parse/urltype.py)
> 的 `detect()` 七类返回值（`URL_TYPES`），以及 [`engine/fetcher.py`](../src/zhihu_downloader/engine/fetcher.py) 的 `resolve_book()` 处理分支。
> 判定顺序即下表顺序（源码自上而下的短路判断）。

## 图例

- ✅ **支持**：可直接下载并导出。
- ⚠️ **兜底 / 有条件**：走通用路径，能否成功取决于页面结构。
- ❌ **不支持**：明确报错并给替代方案，不会静默失败。

## 主表

| # | `detect()` 返回值 | 链接形态（示例） | 判定规则（源码） | 支持状态 | 行为说明 | 替代方案 / 下一步 |
|---|---|---|---|---|---|---|
| 1 | `section` | `https://www.zhihu.com/market/paid_column/1234/section/5678` | 主机为知乎系 且 path 含 `/market/paid_column/` 且含 `/section/` | ✅ | 按**单章**下载：抓该页正文 → 解析 → 清洗 → 导出 1 章的书 | 要整本请改贴专栏目录页链接（第 2 行） |
| 2 | `column` | `https://www.zhihu.com/market/paid_column/1234567890123456789` | 主机为知乎系 且 path 含 `/market/paid_column/`（无 `/section/`） | ✅ | 先抓**目录页**得到全部章节（`parse_toc`），再按 `--workers` **并行**逐章取章（吞吐上限始终是 `rate_limit`，默认 2 请求/秒），支持断点续传与追更 | 目录解析不出章节时报 `ParseError`（多为未登录/无权限）→ `zhihu-downloader login` 后重试 |
| 3 | `answer` | `https://www.zhihu.com/question/123456/answer/789012` | path 含 `/answer/` | ✅ | 按**单篇**下载回答正文：`resolve_book` 走 `fetcher._SINGLE_PAGE_TYPES` 分支，产出只含 1 章的 `BookMeta`；CLI `download --url` 与 GUI 输入框同义 | 若内容属于盐选连载，建议直接贴所属专栏的 `market/paid_column` 链接一次拿整本 |
| 4 | `zhuanlan` | `https://zhuanlan.zhihu.com/p/123456` | 主机等于 `zhuanlan.zhihu.com`（或其子域） | ✅ | 按**单篇**下载专栏文章正文（同第 3 行的 `_SINGLE_PAGE_TYPES` 分支）；v5 起从 `column` 中独立出来，不再误当目录页 | 想备份整个专栏：贴专栏首页链接会落到兜底行，建议逐篇下载 |
| 5 | `app_column` | `https://story.zhihu.com/manuscript/paid_column/1234` | 主机以 `story.zhihu.com` 结尾 且**不**满足第 6 行的章节条件 | ❌ | 「仅 APP 内阅读」内容，需知乎移动端私有 `mst`/`xsec` 设备签名；本项目按红线**不做逆向**，直接报 `UnsupportedUrlError` 并附具体替换 URL | 把 `story.zhihu.com/manuscript/paid_column/<专栏ID>` 替换为 `www.zhihu.com/market/paid_column/<专栏ID>`，用网页版链接重新下载（前提：该内容网页端可读且你已购） |
| 6 | `app_section` | `https://story.zhihu.com/manuscript/paid_column/1234/5678` | 主机以 `story.zhihu.com` 结尾 且 path 匹配 `MANUSCRIPT_PATTERN`（`/manuscript/paid_column/\d+(/\d+)?`）且斜杠数 ≥ 4 | ❌ | 同上（APP 单章） | 把 `story.zhihu.com/manuscript/paid_column/<专栏ID>/<章节ID>` 替换为 `www.zhihu.com/market/paid_column/<专栏ID>/section/<章节ID>` |
| 7 | `unknown` | `https://example.com/x`、空串、乱码、无法解析的 URL | 主机不是 `zhihu.com` 及其子域，或 URL 解析抛错 | ❌ | 直接报 `UnsupportedUrlError`，中文提示「不是知乎系域名或格式有误」；解析异常不会崩栈 | 改贴知乎回答 / 盐选专栏 / 章节链接；Web 端 `POST /api/download` 另有同解析器闸门（见下方「闸门口径」） |
| — | （兜底）`column` | `https://www.zhihu.com/topic/19550980` 等其余知乎页 | 前六条都不匹配的知乎系页面 | ⚠️ | 沿用旧版行为按**专栏目录页**处理：能解析出章节列表就下载，解析不出就报 `ParseError`（消息含下一步） | 非盐选内容建议逐篇用 `answer` / `zhuanlan` 链接下载 |

## 中断与失败行为（与链接类型正交）

| 情形 | 支持状态 | 实际行为 | 下一步 |
|---|---|---|---|
| 单章最终失败（重试耗尽 / 403 / 解析失败） | ✅ 可续传 | 置 abort 标志**中止整本**并 `emit(error)`；此前逐章写入的正文与状态**原样保留**在 `<输出目录>/.zhihu_state/`（消息形状见下方注） | 按原因处理（多数是 Cookie 掉了 → `zhihu-downloader login`），然后**重跑同一条命令 / 重贴同一个链接**，已完成章节自动跳过 |
| 中途关窗口、断电 | ✅ 可续传 | 每完成一章立即原子落盘（先 `.tmp` 再 `os.replace`），已计入进度的章节不会丢 | 同上：重跑同一链接续传 |
| **状态文件**损坏（唯一需要手工的损坏路径） | ⚠️ 需一步手工 | 抛 `CheckpointError`，中文消息直接给两条出路：「删除该文件或加 `--no-resume` 重新下载整本」 | 删掉 `.zhihu_state/` 下对应状态文件（保留续传），或加 `--no-resume` 走逃生门（放弃续传，重下整本） |
| 章节正文缓存缺失或损坏 | ✅ 自愈 | `get_done_urls()` 把「文件在但解析不出」的章节排除在完成集合外 → 续传时走正常重取管线并回填缓存；导出阶段若缓存不可用也会现场重抓该章（R1-m1），**不会**抛「请加 `--no-resume`」把续传带进死路 | 无需操作 |
| 全部成功 | ✅ 保留断点复用 | 状态与章节缓存**保留**（v5.0 裁决 R1-M4）：同链接重跑=秒级重导出，「追更」只抓新章 | `zhihu-downloader doctor` 的 `磁盘占用` 项报出缓存体量，超 500MB 给 prune 指引（统计范围见下方「说明与限制」）；也可手工删 `<输出目录>/.zhihu_state/` |

> `--no-resume` 是**逃生门**不是日常选项：它会先清空断点再从第 1 章重来。
>
> 失败消息形状：「第 N 章《…》下载失败：<中文原因>；已完成章节已保留，可续传」；异常不是 `SaltError` 派生类时，
> 后面还会补一句「请重新运行同一命令续传剩余章节」。照这句话做就是正确出路，不必猜。
> 失败续传与 `--workers` 都不会提高每秒请求数 —— 吞吐上限始终是 `rate_limit`（默认 2 请求/秒）。

## 说明与限制

- **单篇 vs 整本**：`fetcher._SINGLE_PAGE_TYPES = {"section", "answer", "zhuanlan"}` 三类一律按单篇文章处理
  （正文页预取后不重复请求）；其余知乎页按目录页处理（抓 `parse_toc`）。CLI 的 `download --url` 与 GUI 输入框
  共用同一个 `download_book`，所以两个入口的链接支持范围完全一致。
- **权限前提**：盐选内容必须是你**本人已购/已订阅**的，且登录 Cookie 含有效的 `z_c0` 与签名必需的 `d_c0`。
  无权限时知乎返回的是付费引导页，解析不出正文 —— 这是设计如此，本工具不绕付费墙。
- **`story.zhihu.com` 的网页版对应关系不是 100% 存在**：只有当同一内容在网页端 `market/paid_column` 下也可读时，
  替换法才有效；纯 APP 独占内容请直接在 App 内阅读。
- **导出可用性不因链接类型而变**：`txt` / `md` / `epub` 三种格式对所有 ✅ 类型一致可用。
- **追更只对整本书有意义**：`answer` / `zhuanlan` / `section` 这类单篇下载后，书架追更通常不会新增章节。
- **提示文本来源**：每类的中文提示由 `urltype.friendly_hint()` 给出，两类 APP 独占链接的提示自带替换示例，
  与 README「支持的链接」表一致；回归测试见 `tests/test_urltype.py`。
- **仿冒域名一律 `unknown`**：`zhihu.com.evil.net`、`notzhihu.com` 都不算知乎系（`_zhihu_host` 只接受等于
  `zhihu.com` 或以 `.zhihu.com` 结尾的主机名），大写主机名先归一化再判定。
- **闸门口径（Web 与引擎一致，R2 加固后）**：`app/server.py` 的 `is_zhihu_url` 与 `engine/client.py` 的目标校验
  都用**与真正发请求的 HTTP 栈同一个解析器**（`urllib3.util.parse_url`）取主机名，并**硬拒含反斜杠与 `@` 的链接**
  —— 这两类字符会让「闸门看到的域名」与「实际连出去的主机」产生差分（指向本机端口或内网地址）。因此
  **含 `@` 或反斜杠的知乎链接一律 400 / 拒绝，这是保护不是 bug**；请求发出后还会对实际落点复校验一次，
  跨域重定向不携带 Cookie（禁默认跟随 + 逐跳域校验 + Cookie 绑域）。书架追更入口（`POST /api/shelf/{id}/update`）
  读磁盘上的 URL，同样先过这道闸与格式白名单。
- **`story.zhihu.com` 下的非手稿路径**（如活动页）按 `app_column` 处理，同样给出「换网页版链接」的提示。
- **`doctor` 磁盘占用的统计范围**：`_check_disk_usage` 汇总的是**默认输出目录**下的 `.zhihu_state`
  （`~/.zhihu_downloader/output/.zhihu_state`，即 GUI 下载落点），阈值 500MB；超限时提示「可在书架移除不再追更的
  书以 prune 缓存」。纯观测项：`info` 级，不计入 doctor 退出码，目录不存在按 0 计、统计失败也不升级为错误。
  **已知边界**：CLI 用 `-o DIR` 下到别处的缓存不在统计范围内（doctor 目前没有 `--output-dir` 参数），那部分只能
  手工删 `DIR/.zhihu_state/`（牺牲续传与追更复用，已导出文件不受影响）；多目录汇总已记 v5.1。

## 相关文档

- [README.md](../README.md) —— 用户视角的能力表与常见问题
- [docs/ARCHITECTURE.md](ARCHITECTURE.md) —— `resolve_book` → 下载 → 导出 的完整数据流
- [docs/ARCHITECTURE_SPEC.md](ARCHITECTURE_SPEC.md) —— §2.3 / §2.8 接口契约
- [docs/ROADMAP.md](ROADMAP.md) —— 「永不做」红线（含不逆向 APP 端签名）
