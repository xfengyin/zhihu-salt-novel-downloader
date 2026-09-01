"""下载编排：解析目录 → 并发取章 → 断点续传 → 导出。

见 docs/ARCHITECTURE_SPEC.md §2.3。要点：

- 并发取章用 ThreadPoolExecutor(workers)，真正的平台友好由 ZhihuClient 内部
  限速（时间槽预约）保证，这里只控制「同时在飞的章节数」；
- 每完成一章立刻写章节缓存并更新状态，因此中断/异常后 resume 可续传；
- 单章最终失败：中止整本并 emit(error)，已完成章节保留在断点里；
- 全部成功后按目录顺序读回正文 → export_book → emit(done)，**保留断点**（R1-M4
  主审裁决：同链接重跑=秒级重导出、追更只抓新章；清理入口是 resume=False 与
  CheckpointStore.prune，不再是「成功即清」）；
- 分工：parse_article 内部已用分类器填 Article.chapter_type、parse_toc 已填
  ChapterRef.type，本层不重复分类，只做「目录优先」的合并；每章在
  parse_article 之后调 parse.cleaner.clean(article) 完成清洗；
- 本层不 import shelf（分层铁律）：需要有序章节 URL 的上层可先 resolve_book，
  再把 BookMeta 通过 download_book(meta=...) 传下来复用。

关于 import：parse/export 由其他 agent 并行开发，本模块按规格路径在函数内
延迟导入（from zhihu_downloader.parse.parser import parse_article 等）。
这样有两个好处：一是 parse/export 尚未落地时本包也能正常 import；二是测试可用
monkeypatch.setitem(sys.modules, "zhihu_downloader.parse.parser", fake) 注入
假模块，做到完全离线、不依赖他人文件。
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from ..errors import ParseError, SaltError, UnsupportedUrlError, ZhihuError
from ..types import Article, BookMeta, BookResult, ChapterRef, ProgressEvent
from .checkpoint import CheckpointStore
from .client import ZhihuClient

if TYPE_CHECKING:  # 仅类型标注，运行时不导入（见模块 docstring）
    from ..export import export_book  # noqa: F401

logger = logging.getLogger(__name__)

__all__ = ["DEFAULT_STATE_SUBDIR", "check_new_chapters", "download_book", "resolve_book"]

#: 断点目录名（位于 output_dir 之下），与规格 §3 的用户状态布局一致。
DEFAULT_STATE_SUBDIR = ".zhihu_state"

#: 按「单篇文章」处理的 URL 类型（其余知乎链接按专栏目录处理）。
_SINGLE_PAGE_TYPES = frozenset({"section", "answer", "zhuanlan"})

#: 仅知乎 APP 内可读、当前无法下载的类型。
_APP_ONLY_TYPES = frozenset({"app_column", "app_section"})

ProgressCallback = Callable[[ProgressEvent], None]


# ----------------------------------------------------------------------
# 内部工具
# ----------------------------------------------------------------------

def _emit(progress: ProgressCallback | None, event: ProgressEvent) -> None:
    """安全地发送进度事件（回调抛错不得影响下载）。"""
    if progress is None:
        return
    try:
        progress(event)
    except Exception:  # pragma: no cover - 防御：UI 回调不应打断下载
        logger.exception("进度回调异常（已忽略）：%s", event.kind)


def _state_dir_for(output_dir: str | Path) -> Path:
    """返回本书断点目录：<output_dir>/.zhihu_state。"""
    return Path(output_dir) / DEFAULT_STATE_SUBDIR


class _Counter:
    """线程安全的「已完成章节数」计数器，用于进度事件的 current 字段。"""

    def __init__(self, start: int = 0) -> None:
        self._value = start
        self._lock = threading.Lock()

    def bump(self) -> int:
        """计数加一并返回新值。"""
        with self._lock:
            self._value += 1
            return self._value

    @property
    def value(self) -> int:
        """当前计数。"""
        with self._lock:
            return self._value


# ----------------------------------------------------------------------
# 目录解析
# ----------------------------------------------------------------------

def resolve_book(client: ZhihuClient, url: str) -> BookMeta:
    """把用户给的链接解析成 BookMeta（书名 + 有序章节列表）。

    Args:
        client: 知乎客户端。
        url: 章节 / 专栏 / 回答 / 知乎专栏链接。

    Returns:
        BookMeta：单篇链接只含 1 章，专栏含全部章节。

    Raises:
        UnsupportedUrlError: 仅 APP 内阅读的链接（消息含 story→market 替换建议），
            或完全无法识别的链接。
        ZhihuError: 目录页请求失败。
        ParseError: 目录页解析不出任何章节。
    """
    meta, _prefetched = _resolve_book(client, url)
    return meta


def _resolve_book(client: ZhihuClient, url: str) -> tuple[BookMeta, dict[str, str]]:
    """resolve_book 的内部版本，附带「已抓到的页面」。

    单篇链接（章节/回答）的正文页本身就是第 1 章，把它一起返回，
    download_book 就不必为同一 URL 再发一次请求。

    Args:
        client: 知乎客户端。
        url: 目标链接。

    Returns:
        (BookMeta, {章节 URL: 已抓取的 HTML})；专栏的目录页不属于任何章节，
        因此第二项通常为空。

    Raises:
        同 resolve_book。
    """
    from zhihu_downloader.parse.parser import parse_article, parse_page_title, parse_toc
    from zhihu_downloader.parse.urltype import detect, friendly_hint

    url_type = detect(url)

    if url_type in _APP_ONLY_TYPES:
        raise UnsupportedUrlError(_app_only_message(url, url_type, friendly_hint(url_type)))
    if url_type == "unknown":
        # I3 反向发现定稿：friendly_hint('unknown') 本身就以「无法识别该链接」开头，
        # 本层不再重复前缀，只把具体链接附在提示后面（用户不会看两遍）。
        raise UnsupportedUrlError(f"{friendly_hint('unknown')}（链接：{url}）")

    html = client.fetch(url)

    if url_type in _SINGLE_PAGE_TYPES:
        article = parse_article(html, url)
        title = article.title or parse_page_title(html) or "未命名内容"
        meta = BookMeta(
            title=title,
            url=url,
            # 章节类型由 parse_article 经分类器填好，这里直接沿用，不重复分类。
            chapters=[
                ChapterRef(url=url, title=title, index=1,
                           type=article.chapter_type or "normal")
            ],
        )
        return meta, {url: html}

    # parse_toc 返回 [] 表示确实解析不到章节（它自己不抛错），由本层负责报错。
    chapters = _normalize_chapters(parse_toc(html, url))
    if not chapters:
        raise ParseError(
            f"未在专栏页解析到任何章节链接：{url}。"
            "请确认链接是否为专栏目录页，以及登录 Cookie 是否仍然有效。"
        )
    title = parse_page_title(html) or chapters[0].title
    logger.info("目录解析完成：%s（%d 章）", title, len(chapters))
    return BookMeta(title=title, url=url, chapters=chapters), {}


def _manuscript_pattern() -> re.Pattern[str] | None:
    """取解析层的移动端路径模式 parse.urltype.MANUSCRIPT_PATTERN。

    用「同一个模式」判定专栏 ID / 章节 ID，保证错误消息里的替换链接与
    detect() 的归类口径一致。解析层若尚未落地或未导出该模式，返回 None，
    由本模块按路径段兜底（不影响功能，只是不再依赖具体实现）。
    """
    import importlib

    try:
        urltype = importlib.import_module("zhihu_downloader.parse.urltype")
    except Exception:  # pragma: no cover - 并行开发期兜底
        return None
    return getattr(urltype, "MANUSCRIPT_PATTERN", None)


def market_replacement(url: str) -> str:
    """把「仅 APP 内阅读」的 story.zhihu.com 链接换算成网页版 market 链接。

    网页版链接可被本工具下载，因此错误消息里给出**可直接粘贴的具体地址**
    （如 .../manuscript/paid_column/123 → https://www.zhihu.com/market/paid_column/123），
    而不是只丢一个 <专栏ID> 占位模板让用户自己改。

    换算优先用解析层的 MANUSCRIPT_PATTERN（与 detect 同一口径）：
    group(1)=专栏 ID、group(2)=章节 ID（单章链接才带上 /section/）。

    Args:
        url: story.zhihu.com 的 APP 内链接。

    Returns:
        换算后的 www.zhihu.com/market/... 链接；结构不认识时返回空字符串。
    """
    try:
        parsed = urlparse(url)
    except ValueError:  # pragma: no cover - 极端畸形 URL
        return ""
    host = (parsed.hostname or "").lower()
    if host != "story.zhihu.com" and not host.endswith(".story.zhihu.com"):
        return ""
    path = parsed.path or ""

    pattern = _manuscript_pattern()
    if pattern is not None:
        match = pattern.search(path)
        if match is not None:
            return _market_url(match.group(1), match.group(2))

    parts = [p for p in path.split("/") if p]
    if len(parts) >= 3 and parts[0] == "manuscript" and parts[1] == "paid_column":
        section_id = parts[3] if len(parts) >= 4 else None
        return _market_url(parts[2], section_id)
    return ""


def _market_url(column_id: str, section_id: str | None) -> str:
    """按网页版地址规则拼替换链接（专栏目录页或单章页）。"""
    base = f"https://www.zhihu.com/market/paid_column/{column_id}"
    return f"{base}/section/{section_id}" if section_id else base


def _app_only_message(url: str, url_type: str, hint: str) -> str:
    """拼出「仅 APP 内阅读」的中文错误消息（含具体替换链接建议）。"""
    message = f"该链接（{url}）仅支持在知乎 APP 内阅读，无法直接下载。{hint}"
    replacement = market_replacement(url)
    if replacement:
        message += f" 请改用网页版链接重试：{replacement}"
    return message


def _normalize_chapters(chapters: Iterable[ChapterRef]) -> list[ChapterRef]:
    """目录结果规范化：按 URL 去重保序、补齐序号，标题为空时用 URL 兜底显示。

    章节类型直接沿用 parse_toc（其内部已用分类器），本层不再分类。

    Args:
        chapters: parse_toc 的原始结果。

    Returns:
        规范化后的章节列表，index 从 1 开始连续编号。
    """
    seen: set[str] = set()
    result: list[ChapterRef] = []
    for ch in chapters:
        url = (ch.url or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        title = (ch.title or "").strip() or url
        result.append(
            ChapterRef(
                url=url,
                title=title,
                index=len(result) + 1,
                type=ch.type or "normal",
            )
        )
    return result


# ----------------------------------------------------------------------
# 整本下载
# ----------------------------------------------------------------------

def _apply_toc_metadata(article: Article, chapter: ChapterRef) -> Article:
    """把目录信息合并进解析结果（标题以目录为准；章节类型目录优先补齐）。

    标题以目录为准：专栏目录里的「番外 / 作者的话」等标记是这本书的章节命名
    权威（正文页 og:title 常是营销标题），导出与附录分组都靠它。
    _normalize_chapters 在无标题时用 URL 兜底，故这里排除等于 URL 的标题。
    章节类型：parse_article 已按正文页标题分类；若它仍是默认 normal 而目录
    标题标明是番外/作者的话，则以目录为准（导出层据此归入附录）。
    """
    toc_title = chapter.title if chapter.title and chapter.title != chapter.url else ""
    article.title = toc_title or article.title or chapter.title
    article.url = article.url or chapter.url
    if chapter.type and chapter.type != "normal" and article.chapter_type in ("", "normal"):
        article.chapter_type = chapter.type
    return article


#: 安装/还原 client.on_retry 的全局锁（只在属性读写与注册表操作期间持有）。
_retry_hook_lock = threading.Lock()


class _RetryDispatcher:
    """共享的 client.on_retry 挂点：把重试分发给各在册 download_book 任务自己的钩子。

    R1-M2：多任务共用一个 client 时，若各自直接覆盖 on_retry，后还原者会把
    先还原者的「还原」再覆盖回去（钩子泄漏），运行期还会把重试事件送进别的
    任务的进度回调（跨任务串流）。改为：第一个任务安装本 dispatcher 并把用户
    原有钩子存为 fallback，后来的任务只往 dispatcher 上注册/注销自己的钩子；
    重试触发时逐个调用在册钩子（钩子自带 URL 归属过滤，见 _make_retry_hook），
    事件天然不互串；最后一个任务注销后 on_retry 原样交还。
    """

    def __init__(self, fallback: Callable[[str, int, float, str], None] | None) -> None:
        self.fallback = fallback
        self._hooks: list[Callable[[str, int, float, str], None]] = []
        self._lock = threading.Lock()

    def add(self, hook: Callable[[str, int, float, str], None]) -> None:
        with self._lock:
            self._hooks.append(hook)

    def remove(self, hook: Callable[[str, int, float, str], None]) -> None:
        with self._lock:
            self._hooks = [h for h in self._hooks if h is not hook]

    @property
    def empty(self) -> bool:
        """当前没有任何任务在册。"""
        with self._lock:
            return not self._hooks

    def __call__(self, url: str, attempt: int, delay: float, reason: str) -> None:
        with self._lock:
            hooks = list(self._hooks)
        for hook in hooks:  # 任务钩子自带过滤，且 _emit 吞异常，这里无需兜底
            hook(url, attempt, delay, reason)
        if self.fallback is not None:
            try:
                self.fallback(url, attempt, delay, reason)
            except Exception:  # pragma: no cover - 用户钩子异常不得打断下载
                logger.exception("on_retry 用户回调异常（已忽略）")


def _install_retry_hook(
    client: ZhihuClient, hook: Callable[[str, int, float, str], None]
) -> Callable[[], None] | None:
    """把任务钩子挂到 client.on_retry 上，返回撤销闭包（不可安装时返回 None）。

    R1-M2：安装与还原都在全局锁内做**身份判定**——每个任务只增删自己注册的
    钩子；dispatcher 空了且当前挂着的仍是它，才把 on_retry 还原成用户原值。
    两个任务共用 client 时谁也不覆盖谁，既不泄漏钩子也不串事件。
    """
    if not hasattr(client, "on_retry"):  # 鸭子类型替身没有该能力：不塞新属性
        return None
    try:
        with _retry_hook_lock:
            current = getattr(client, "on_retry", None)
            dispatcher = current if isinstance(current, _RetryDispatcher) \
                else _RetryDispatcher(current)
            dispatcher.add(hook)
            client.on_retry = dispatcher
    except Exception:  # pragma: no cover - 只可能由不可写属性触发
        logger.debug("该 client 的 on_retry 不可写，retry 进度事件将缺席")
        return None

    def restore() -> None:
        with _retry_hook_lock:
            dispatcher.remove(hook)
            if dispatcher.empty and getattr(client, "on_retry", None) is dispatcher:
                client.on_retry = dispatcher.fallback

    return restore


def download_book(
    client: ZhihuClient,
    url: str,
    fmt: str = "md",
    output_dir: str | Path = ".",
    progress: ProgressCallback | None = None,
    resume: bool = True,
    workers: int = 3,
    meta: BookMeta | None = None,
) -> BookResult:
    """下载一本书（或单章）并导出，支持断点续传与并发取章。

    进度事件序列（正常路径）：toc → 每章一个 chapter（client 内部重试时穿插
    retry）→ export → done；失败路径：toc → 若干 chapter →（导出阶段失败时先
    export 再）error，并抛异常（R1-m7：导出失败同样发 error 事件）。两种失败
    都保留断点，重跑同一命令自动续传/重新导出。

    R1-M4（主审裁决）：全部成功后也**保留**断点（state+bodies），因此同一链接
    重跑=秒级重导出、连载追更只抓新增章节；要彻底重来用 resume=False，要清理
    用 CheckpointStore.prune（书架移除入口）。

    Args:
        client: 知乎客户端（内部限速，可多线程共用）。
        url: 专栏 / 章节 / 回答链接。
        fmt: 导出格式（txt/md/epub，由 export 层校验）。
        output_dir: 导出目录；断点写在其下的 .zhihu_state 子目录。
        progress: 进度回调（CLI 进度条与 Web SSE 共用）。
        resume: True 时跳过断点里「已完成且正文可解析」的章节（R1-m1：坏缓存
            视同未完成，自动重取）；False 先清空断点再全量重下。
        workers: 同时在飞的章节数（下限 1；平台友好由 client 限速保证）。
        meta: 已解析好的目录（可选）。上层（CLI/server）若需要有序章节 URL
            交给 shelf 记账，可先调 resolve_book 再把结果传进来，避免重复请求
            目录页。为 None 时本函数自己解析。

    Returns:
        BookResult（含导出文件路径与跳过的章节数）。有序章节 URL 不在返回值里
        （types.BookResult 契约固定），需要者请由 meta / resolve_book 取得。

    Raises:
        UnsupportedUrlError: 链接类型不支持。
        CheckpointError: 断点文件损坏或不可写。
        ZhihuError / ParseError / ExportError: 请求、解析或导出失败
            （消息为中文可操作提示）。
    """
    from zhihu_downloader.export import export_book
    from zhihu_downloader.parse.cleaner import clean
    from zhihu_downloader.parse.parser import parse_article

    prefetched: dict[str, str] = {}
    if meta is None:
        meta, prefetched = _resolve_book(client, url)
    total = len(meta.chapters)
    store = CheckpointStore(_state_dir_for(output_dir), book_key=url)

    if not resume:
        store.clear()

    done_urls = store.get_done_urls()
    pending = [ch for ch in meta.chapters if ch.url not in done_urls]
    skipped = total - len(pending)

    store.set_meta(meta.title, total, fmt)
    if skipped:
        logger.info("续传：跳过已完成的 %d/%d 章", skipped, total)
    _emit(
        progress,
        ProgressEvent(
            kind="toc", current=skipped, total=total, title=meta.title,
            message=f"共 {total} 章" + (f"，续传跳过 {skipped} 章" if skipped else ""),
        ),
    )

    titles = {ch.url: ch.title for ch in meta.chapters}
    # 本次运行已抓到的正文留在内存里：导出时优先用它，避免依赖共享的章节缓存
    # 文件（同 URL 可能被另一个并发任务清理掉）。
    collected: dict[str, Article] = {}
    counter = _Counter(skipped)
    abort = threading.Event()
    failures: list[tuple[ChapterRef, BaseException]] = []
    failures_lock = threading.Lock()

    def fetch_one(chapter: ChapterRef) -> None:
        """取单章：fetch → parse → clean → 写断点 → emit(chapter)。"""
        if abort.is_set():  # 已有章节彻底失败，不再继续消耗请求
            return
        try:
            html = prefetched.get(chapter.url)
            if html is None:
                html = client.fetch(chapter.url)
            article = _apply_toc_metadata(clean(parse_article(html, chapter.url)), chapter)
            store.put_chapter(chapter.url, article)
            collected[chapter.url] = article
        except BaseException as exc:  # noqa: BLE001 - 汇总后由主线程决定中止
            with failures_lock:
                failures.append((chapter, exc))
            abort.set()
            return
        current = counter.bump()
        _emit(
            progress,
            ProgressEvent(kind="chapter", current=current, total=total,
                          title=article.title or chapter.title),
        )

    # 把 client 的内部重试暴露成 retry 事件。on_retry 是**可选能力**：只在客户端
    # 已声明该属性（ZhihuClient 一定声明）时才挂回调，绝不往调用方的鸭子类型替身
    # 上塞新属性；没有该能力时只是少一类 retry 事件，不影响下载本身。
    # R1-M2：多任务共用 client 时不再各自覆盖 on_retry——安装的是共享
    # _RetryDispatcher，每个任务只注册/注销自己的钩子，还原走身份判定，
    # 杜绝「后还原者覆盖先还原者」造成的钩子泄漏与跨任务事件串流。
    restore_hook = _install_retry_hook(
        client, _make_retry_hook(progress, counter, total, titles)
    )
    try:
        _run_chapters(pending, fetch_one, workers)
    finally:
        if restore_hook is not None:
            restore_hook()

    if failures:
        chapter, exc = failures[0]
        reason = str(exc) or exc.__class__.__name__
        message = f"第 {chapter.index} 章《{chapter.title}》下载失败：{reason}"
        logger.error("%s（已完成的 %d 章保留在断点，可续传）", message, counter.value)
        _emit(
            progress,
            ProgressEvent(kind="error", current=counter.value, total=total,
                          title=chapter.title, message=message + "；已完成章节已保留，可续传"),
        )
        if isinstance(exc, SaltError):
            raise exc
        raise ZhihuError(message + "。请重新运行同一命令续传剩余章节。") from exc

    def refetch_one(chapter: ChapterRef) -> Article:
        """缓存缺失/损坏时的现场自愈重抓（R1-m1）：fetch → parse → clean → 回填缓存。

        只在「跳过该章后、导出前缓存又没了/坏了」的竞态里兜底；常规坏缓存已被
        get_done_urls 的「存在且可解析」判定挡在门外（走正常重抓管线）。
        """
        html = client.fetch(chapter.url)
        article = _apply_toc_metadata(clean(parse_article(html, chapter.url)), chapter)
        store.put_chapter(chapter.url, article)
        logger.info("章节缓存缺失或损坏，已现场重取并回填：《%s》", chapter.title)
        return article

    try:
        articles = _collect_articles(store, meta, collected, refetch=refetch_one)
    except Exception as exc:  # 自愈重抓也可能再次失败：同样对齐 §2.3 失败路径（R1-m7 精神）
        reason = str(exc) or exc.__class__.__name__
        message = f"《{meta.title}》章节正文取回失败：{reason}"
        logger.error("%s（断点已保留，修复后重跑同一命令可续传）", message)
        _emit(
            progress,
            ProgressEvent(kind="error", current=total, total=total, title=meta.title,
                          message=message + "；断点已保留，修复后重跑同一命令即可续传"),
        )
        raise
    _emit(progress, ProgressEvent(kind="export", current=total, total=total,
                                  title=meta.title, message=f"正在导出 {fmt}"))
    try:
        files = export_book(meta.title, articles, fmt, output_dir)
    except Exception as exc:  # R1-m7：失败路径必须发 error 事件（对齐 §2.3），再原样抛
        reason = str(exc) or exc.__class__.__name__
        message = f"《{meta.title}》导出 {fmt} 失败：{reason}"
        logger.error("%s（断点已保留，修复后重跑同一命令可直接重新导出）", message)
        _emit(
            progress,
            ProgressEvent(kind="error", current=total, total=total, title=meta.title,
                          message=message + "；断点已保留，修复后重跑同一命令即可重新导出"),
        )
        raise

    # R1-M4（主审裁决）：成功后**保留**断点 state+bodies，不再 store.clear()——
    # 同链接重跑=秒级重导出（只请求目录页），追更只抓新章（README「只下新增章节」
    # 的承诺靠此兑现）。清理入口：resume=False（本函数开头已 clear）与
    # CheckpointStore.prune（CLI shelf remove / server DELETE /api/shelf 由 S1/I3 接线）。

    result = BookResult(
        title=meta.title,
        url=meta.url,
        chapters=len(articles),
        files=[str(f) for f in files],
        skipped_existing=skipped,
    )
    _emit(progress, ProgressEvent(kind="done", current=total, total=total, title=meta.title,
                                  message=f"完成：{len(result.files)} 个文件"))
    return result


def _make_retry_hook(
    progress: ProgressCallback | None,
    counter: _Counter,
    total: int,
    titles: dict[str, str],
) -> Callable[[str, int, float, str], None]:
    """构造 client.on_retry 回调：把内部重试转成 retry 进度事件。

    R1-M2：共享 dispatcher 会把重试广播给所有在册任务，故钩子只对「本任务
    目录内的 URL」发声（titles 即本任务的章节表）——别的任务在重试别的 URL
    时，本回调直接返回，进度事件不互串。
    """

    def hook(url: str, attempt: int, delay: float, reason: str) -> None:
        if url not in titles:  # 其他任务的重试，与本任务无关
            return
        _emit(
            progress,
            ProgressEvent(
                kind="retry",
                current=counter.value,
                total=total,
                title=titles.get(url, url),
                message=f"第 {attempt} 次重试（{delay:.0f}s 后）：{reason}",
            ),
        )

    return hook


def _run_chapters(
    pending: list[ChapterRef], work: Callable[[ChapterRef], None], workers: int
) -> None:
    """并发执行 work(chapter)，等全部收尾后返回。

    Args:
        pending: 待下载章节。
        work: 单章工作函数（自行捕获异常，不外抛业务错误）。
        workers: 线程数（下限 1）。
    """
    if not pending:
        return
    max_workers = max(1, int(workers))
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="zhihu-fetch") as pool:
        futures: list[Future] = [pool.submit(work, ch) for ch in pending]
        for fut in futures:
            fut.result()  # work 不抛业务异常，这里只是确保全部收尾


def _collect_articles(
    store: CheckpointStore,
    meta: BookMeta,
    collected: dict[str, Article] | None = None,
    refetch: Callable[[ChapterRef], Article] | None = None,
) -> list[Article]:
    """按目录顺序取回全部章节正文：本次运行的内存结果优先，其次断点缓存。

    R1-m1：缓存缺失/损坏（被并发任务清理、或磁盘上留了坏文件）时不再抛
    「请加 --no-resume」——那与「自愈重取」的承诺相反，等于把续传带进死路。
    给了 refetch 就现场重抓该章（fetch + parse + clean）并回填缓存；
    没给 refetch 时（防御性兜底）才报 ParseError。

    Args:
        store: 断点存储（续传进来的章节从这里读回）。
        meta: 已解析的目录（决定顺序）。
        collected: 本次运行已抓取的章节正文（可缺省）。
        refetch: 缓存不可用时的自愈重抓函数（fetch → parse → clean → 回填）。

    Raises:
        ParseError: 某章正文既不在内存也不在缓存，且未提供 refetch。
    """
    collected = collected or {}
    articles: list[Article] = []
    for chapter in meta.chapters:
        article = collected.get(chapter.url)
        if article is None:
            article = store.get_article(chapter.url)
        if article is None and refetch is not None:
            article = refetch(chapter)
        if article is None:
            raise ParseError(
                f"章节缓存缺失：《{chapter.title}》（{chapter.url}）。"
                "请加 --no-resume 重新下载整本。"
            )
        articles.append(article)
    return articles


# ----------------------------------------------------------------------
# 追更
# ----------------------------------------------------------------------

def check_new_chapters(client: ZhihuClient, url: str, known_urls: list[str]) -> list[ChapterRef]:
    """比对已知章节 URL，返回尚未下载的新章节（保持目录顺序）。

    Args:
        client: 知乎客户端。
        url: 专栏（或单章）链接。
        known_urls: 已下载的章节 URL 列表。

    Returns:
        新章节 ChapterRef 列表；无新章节时为空列表。

    Raises:
        UnsupportedUrlError / ZhihuError / ParseError: 同 resolve_book。
    """
    meta = resolve_book(client, url)
    known = {u for u in known_urls if u}
    return [ch for ch in meta.chapters if ch.url not in known]
