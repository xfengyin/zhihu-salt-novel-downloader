"""断点续传管理器"""

from __future__ import annotations

import json
from pathlib import Path


class CheckpointManager:
    """断点续传管理器"""

    def __init__(
        self,
        output_dir: str | Path,
        article_title: str,
    ) -> None:
        """
        初始化断点管理器

        Args:
            output_dir: 输出目录
            article_title: 文章标题
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.article_title = article_title
        self._checkpoint_file = self.output_dir / f".checkpoint_{self._sanitize_name()}.json"

    def _sanitize_name(self) -> str:
        """生成安全的文件名"""
        import re
        safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", self.article_title)
        return safe[:50]

    def get_checkpoint_file(self) -> Path:
        """获取checkpoint文件路径"""
        return self._checkpoint_file

    def save_checkpoint(self, downloaded_ids: set[str]) -> None:
        """
        保存断点

        Args:
            downloaded_ids: 已下载的章节ID集合
        """
        data = {
            "article_title": self.article_title,
            "downloaded_ids": list(downloaded_ids),
        }

        with open(self._checkpoint_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_checkpoint(self) -> set[str]:
        """
        加载断点

        Returns:
            已下载的章节ID集合
        """
        if not self._checkpoint_file.exists():
            return set()

        try:
            with open(self._checkpoint_file, "r", encoding="utf-8") as f:
                data: dict[str, list[str]] = json.load(f)
            return set(data.get("downloaded_ids", []))
        except (json.JSONDecodeError, IOError):
            return set()

    def clear_checkpoint(self) -> None:
        """清除断点"""
        if self._checkpoint_file.exists():
            self._checkpoint_file.unlink()

    def has_checkpoint(self) -> bool:
        """检查是否存在断点"""
        return self._checkpoint_file.exists()
