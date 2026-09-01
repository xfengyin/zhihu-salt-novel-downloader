"""断点续传存储：原子 JSON 状态 + 章节正文缓存。

目录布局（state_dir 默认为 <output_dir>/.zhihu_state）：

    <state_dir>/<sha1(book_key)[:16]>.json      # 本书状态（标题/总数/格式/已完成 URL）
    <state_dir>/chapters/<sha1(url)[:16]>.json  # 单章正文缓存（Article.to_dict()）

铁律落实：
- 所有 JSON 写入都是「先写 .tmp 再 os.replace」的原子写，进程被杀不会留半截文件；
- 状态文件损坏时 load() 抛 CheckpointError（中文消息），由上层决定清理重来；
- 章节缓存损坏时 get_article() 返回 None（视为未下载，自动重取），避免整本卡死；
  get_done_urls 同样把「存在但不可解析」的正文排除在完成集合之外（R1-m1），
  续传遇到坏缓存走正常重取管线，而不是导出阶段才炸、把用户逼上 --no-resume；
- 下载成功后断点**保留**（R1-M4 主审裁决：秒级重导出/追更只抓新章），显式清理
  入口是 prune()（书架移除）与 fetcher 的 resume=False。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from ..errors import CheckpointError
from ..types import Article

logger = logging.getLogger(__name__)

__all__ = ["CheckpointStore", "key_hash"]


def key_hash(raw: str) -> str:
    """返回用于文件名的稳定短哈希：sha1(raw) 前 16 位十六进制。

    Args:
        raw: 任意字符串（书键或章节 URL）。

    Returns:
        16 字符的十六进制摘要片段。
    """
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _tmp_name(path: Path) -> str:
    """并发安全的临时文件名：带上 pid + 线程 id，避免两个写入者互相覆盖。"""
    return f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """原子写 JSON：同目录唯一 .tmp + os.replace，权限 0600（含正文，属个人内容）。

    并发下另一个任务可能正好在清理章节缓存目录（rmdir），因此写失败且原因是
    「目录不存在」时重建父目录重试一次，而不是把 CheckpointError 抛给用户。

    Args:
        path: 目标文件路径。
        payload: 可 JSON 序列化的字典。

    Raises:
        CheckpointError: 序列化或落盘失败（中文消息，含下一步建议）。
    """
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    last_error: OSError | None = None
    for _attempt in range(2):
        tmp = path.with_name(_tmp_name(path))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(text, encoding="utf-8")
            try:
                os.chmod(tmp, 0o600)
            except OSError:  # pragma: no cover - 某些文件系统不支持 chmod
                pass
            os.replace(tmp, path)
            return
        except FileNotFoundError as exc:  # 父目录被并发清理：重建后重试
            last_error = exc
            logger.debug("断点目录被并发移除，重建重试：%s", path.parent)
            continue
        except OSError as exc:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:  # pragma: no cover - 清理失败不再抛错
                logger.debug("临时文件清理失败：%s", tmp)
            raise CheckpointError(
                f"写入断点文件失败：{path}（{exc}）。请检查磁盘空间与目录写权限后重试。"
            ) from exc
    raise CheckpointError(
        f"写入断点文件失败：{path}（{last_error}）。请检查磁盘空间与目录写权限后重试。"
    )


class CheckpointStore:
    """一本书的断点存储（线程安全）。

    状态文件记录「哪些章节已完成」，章节正文单独缓存成文件，因此续传时既能
    跳过已完成章节，也能在全部完成后按目录顺序读回正文用于导出。
    """

    def __init__(self, state_dir: Path, book_key: str) -> None:
        """初始化存储。

        Args:
            state_dir: 状态目录（通常是 <output_dir>/.zhihu_state）。
            book_key: 书键（一般用专栏 URL），决定状态文件名。
        """
        self.state_dir = Path(state_dir)
        self.book_key = book_key
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # 路径
    # ------------------------------------------------------------------

    @property
    def state_path(self) -> Path:
        """本书状态文件路径。"""
        return self.state_dir / f"{key_hash(self.book_key)}.json"

    @property
    def chapters_dir(self) -> Path:
        """章节正文缓存目录。"""
        return self.state_dir / "chapters"

    def chapter_path(self, url: str) -> Path:
        """某章节正文缓存文件路径。

        Args:
            url: 章节 URL。

        Returns:
            <state_dir>/chapters/<sha1(url)[:16]>.json
        """
        return self.chapters_dir / f"{key_hash(url)}.json"

    # ------------------------------------------------------------------
    # 状态读写
    # ------------------------------------------------------------------

    def load(self) -> dict[str, Any]:
        """读取状态字典。

        Returns:
            状态内容；状态文件不存在时返回空字典。

        Raises:
            CheckpointError: 文件损坏（非法 JSON）或结构不是对象。
        """
        path = self.state_path
        if not path.exists():
            return {}
        with self._lock:
            try:
                raw = path.read_text(encoding="utf-8")
            except OSError as exc:
                raise CheckpointError(f"读取断点文件失败：{path}（{exc}）") from exc
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise CheckpointError(
                    f"断点文件已损坏：{path}（{exc}）。"
                    "请删除该文件或加 --no-resume 重新下载整本。"
                ) from exc
            if not isinstance(data, dict):
                raise CheckpointError(
                    f"断点文件格式异常：{path}（顶层应为 JSON 对象）。"
                    "请删除该文件或加 --no-resume 重新下载整本。"
                )
            return data

    def save(self, data: dict[str, Any]) -> None:
        """原子写入状态字典。

        Args:
            data: 要保存的状态。

        Raises:
            CheckpointError: 写入失败。
        """
        with self._lock:
            _atomic_write_json(self.state_path, data)

    def set_meta(self, title: str, total: int, fmt: str) -> None:
        """写入书名/章节总数/导出格式等元信息（保留已有的 done_urls）。

        Args:
            title: 书名。
            total: 目录解析出的章节总数。
            fmt: 导出格式（txt/md/epub）。
        """
        with self._lock:
            data = self.load()
            data["book_key"] = self.book_key
            data["title"] = title
            data["total"] = int(total)
            data["format"] = fmt
            done = [u for u in data.get("done_urls", []) if isinstance(u, str)]
            data["done_urls"] = done
            self.save(data)

    def get_meta(self) -> dict[str, Any]:
        """返回状态里的元信息副本（title/total/format/done_urls）。"""
        with self._lock:
            return dict(self.load())

    # ------------------------------------------------------------------
    # 章节正文缓存
    # ------------------------------------------------------------------

    def put_chapter(self, url: str, article: Article) -> None:
        """缓存一章正文并把 URL 记入已完成集合（先写正文，后更新状态）。

        顺序很重要：只有正文落盘成功后状态里才算完成，续传时不会读到空章节。

        Args:
            url: 章节 URL（作为缓存键，优先于 article.url）。
            article: 解析并清洗后的章节内容。

        Raises:
            CheckpointError: 正文或状态写入失败。
        """
        with self._lock:
            _atomic_write_json(self.chapter_path(url), article.to_dict())
            data = self.load()
            done = [u for u in data.get("done_urls", []) if isinstance(u, str)]
            if url not in done:
                done.append(url)
            data["done_urls"] = done
            data["book_key"] = self.book_key
            self.save(data)

    def get_article(self, url: str) -> Article | None:
        """读回某章正文缓存。

        Args:
            url: 章节 URL。

        Returns:
            Article 实例；缓存不存在或损坏时返回 None（视为未下载）。
        """
        path = self.chapter_path(url)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("章节缓存损坏，将重新下载：%s（%s）", path, exc)
            return None
        if not isinstance(raw, dict):
            logger.warning("章节缓存格式异常，将重新下载：%s", path)
            return None
        try:
            return Article.from_dict(raw)
        except (KeyError, TypeError) as exc:
            logger.warning("章节缓存无法还原为 Article，将重新下载：%s（%s）", path, exc)
            return None

    def get_done_urls(self) -> set[str]:
        """返回状态中记录的已完成章节 URL 集合（仅统计正文存在且可解析的）。

        R1-m1：「完成」的标准从「文件存在」升级为「存在且可解析」——损坏缓存
        不再被当作已完成，否则续传会一路跳过、直到导出阶段才炸出 ParseError，
        把用户逼上 --no-resume 全量重下的死路（与「自愈重取」的承诺相反）。
        每个坏文件由 get_article 记 1 次 warning（不重复刷屏）。
        """
        with self._lock:
            data = self.load()
        urls = {u for u in data.get("done_urls", []) if isinstance(u, str)}
        return {u for u in urls if self.get_article(u) is not None}

    # ------------------------------------------------------------------
    # 清理
    # ------------------------------------------------------------------

    def prune(self, book_key: str | None = None) -> None:
        """删除某本书的状态与其章节正文缓存（R1-M4 的显式清理入口）。

        与 clear() 的区别：clear 是「重下前的自我清理」，会保护其他书状态还在
        引用的正文（并发下载不误伤）；prune 是「这本书彻底不要了」的显式清理
        （CLI shelf remove / server DELETE /api/shelf 接线），连被兄弟状态引用
        的正文也一并删除——即便误删，对方的 get_done_urls 也会把缺失正文视为
        未完成而自愈重取，不会卡死。

        幂等：文件/目录不存在不报错。

        Args:
            book_key: 要清理的书键（一般是专栏 URL）；None 表示 self.book_key。

        Raises:
            CheckpointError: 删除失败（中文消息，含下一步建议）。
        """
        key = self.book_key if book_key is None else book_key
        target = CheckpointStore(self.state_dir, key)
        with self._lock:
            data: dict[str, Any] = {}
            try:
                data = target.load()
            except CheckpointError as exc:
                logger.warning("断点文件损坏，prune() 直接删除：%s", exc)
            for url in [u for u in data.get("done_urls", []) if isinstance(u, str)]:
                try:
                    target.chapter_path(url).unlink(missing_ok=True)
                except OSError:  # pragma: no cover
                    logger.debug("章节缓存删除失败：%s", url)
            try:
                target.state_path.unlink(missing_ok=True)
            except OSError as exc:
                raise CheckpointError(
                    f"删除断点文件失败：{target.state_path}（{exc}）。请检查目录写权限。"
                ) from exc
            self._prune_chapters_dir()

    def total_bytes(self) -> int:
        """整个断点目录（所有书的状态 + 章节正文缓存）占用的磁盘字节数。

        供 doctor 报告磁盘占用（S2 接线）。R1-M4 之后断点成功后保留，占用会
        随书架增长，因此需要这个观测口。目录不存在返回 0；单个文件读不动
        （并发删除竞态）跳过不报错。
        """
        total = 0
        try:
            entries = list(self.state_dir.rglob("*"))
        except OSError:  # pragma: no cover - 目录不可读
            return 0
        for path in entries:
            try:
                if path.is_file():
                    total += path.stat().st_size
            except OSError:  # pragma: no cover - 并发删除竞态
                continue
        return total

    def clear(self) -> None:
        """删除本书状态与其章节缓存（幂等，文件不存在不报错）。

        章节缓存按 URL 命名、可能被同目录下另一本书共用，因此先扫描兄弟状态
        文件，跳过「别人还在引用」的正文，避免并发下载/续传互相删缓存。
        """
        with self._lock:
            data: dict[str, Any] = {}
            try:
                data = self.load()
            except CheckpointError as exc:
                logger.warning("断点文件损坏，clear() 直接删除：%s", exc)
            mine = [u for u in data.get("done_urls", []) if isinstance(u, str)]
            protected = self._urls_referenced_by_others()
            for url in mine:
                if url in protected:
                    logger.debug("章节缓存被其他任务引用，跳过删除：%s", url)
                    continue
                try:
                    self.chapter_path(url).unlink(missing_ok=True)
                except OSError:  # pragma: no cover
                    logger.debug("章节缓存删除失败：%s", url)
            try:
                self.state_path.unlink(missing_ok=True)
            except OSError as exc:
                raise CheckpointError(
                    f"删除断点文件失败：{self.state_path}（{exc}）。请检查目录写权限。"
                ) from exc
            self._prune_chapters_dir()

    def _urls_referenced_by_others(self) -> set[str]:
        """收集同目录下**其他**书的状态仍引用的章节 URL（清理时保护它们）。

        Returns:
            其他状态文件 done_urls 的并集；本书自己的状态不计入。
        """
        urls: set[str] = set()
        try:
            siblings = list(self.state_dir.glob("*.json"))
        except OSError:  # pragma: no cover - 目录不可读
            return urls
        for path in siblings:
            if path == self.state_path:
                continue
            try:
                other = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                logger.debug("兄弟断点文件读不动，跳过：%s", path)
                continue
            if isinstance(other, dict):
                urls.update(u for u in other.get("done_urls", []) if isinstance(u, str))
        return urls

    def _prune_chapters_dir(self) -> None:
        """空章节目录顺手删掉；但同目录还有其他书的状态时保留（并发安全）。"""
        try:
            if not self.chapters_dir.is_dir():
                return
            if any(self.state_dir.glob("*.json")):
                return  # 还有别的任务/书在用，留着空目录，避免 rmdir 竞态
            if any(self.chapters_dir.iterdir()):
                return
            self.chapters_dir.rmdir()
        except OSError:  # pragma: no cover - 并发下目录可能正被他人使用
            logger.debug("章节缓存目录清理跳过：%s", self.chapters_dir)
