"""断点续传管理器 - 原子性写入"""

import json
import time
import logging
import tempfile
from pathlib import Path
from typing import Set, Optional, List, Dict, Any


logger = logging.getLogger(__name__)


class CheckpointManager:
    """断点续传管理器 - 支持原子性写入"""

    CHECKPOINT_VERSION = 2

    def __init__(self, output_dir: str, article_title: str):
        self.output_dir = Path(output_dir)
        self.article_title = self._sanitize_filename(article_title)
        self.checkpoint_dir = self.output_dir / '.checkpoints'
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def _sanitize_filename(self, filename: str) -> str:
        illegal_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
        for char in illegal_chars:
            filename = filename.replace(char, '_')
        return filename[:100]

    def get_checkpoint_file(self) -> Path:
        return self.checkpoint_dir / f"{self.article_title}.json"

    def save_checkpoint(self, downloaded_ids: Set[str], metadata: Optional[Dict[str, Any]] = None) -> None:
        checkpoint_file = self.get_checkpoint_file()
        temp_file = self.checkpoint_dir / f"{self.article_title}.tmp"

        data = {
            'version': self.CHECKPOINT_VERSION,
            'article_title': self.article_title,
            'downloaded_ids': sorted(list(downloaded_ids)),
            'count': len(downloaded_ids),
            'timestamp': time.time(),
            'metadata': metadata or {}
        }

        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            temp_file.replace(checkpoint_file)
            logger.debug(f"检查点已保存: {len(downloaded_ids)} 个章节")

        except Exception as e:
            if temp_file.exists():
                temp_file.unlink()
            logger.error(f"保存检查点失败: {e}")
            raise

    def load_checkpoint(self) -> Set[str]:
        checkpoint_file = self.get_checkpoint_file()

        if not checkpoint_file.exists():
            return set()

        try:
            with open(checkpoint_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            version = data.get('version', 1)
            if version < self.CHECKPOINT_VERSION:
                data = self._migrate_checkpoint(data)

            ids = set(data.get('downloaded_ids', []))
            logger.info(f"已加载检查点: {len(ids)} 个章节")
            return ids

        except Exception as e:
            logger.warning(f"加载检查点失败: {e}")
            return set()

    def _migrate_checkpoint(self, data: Dict[str, Any]) -> Dict[str, Any]:
        data['version'] = self.CHECKPOINT_VERSION
        data['timestamp'] = time.time()
        data['metadata'] = data.get('metadata', {})
        return data

    def clear_checkpoint(self) -> None:
        checkpoint_file = self.get_checkpoint_file()

        if checkpoint_file.exists():
            checkpoint_file.unlink()
            logger.info("检查点已清除")

    def get_progress(self) -> Optional[Dict[str, Any]]:
        checkpoint_file = self.get_checkpoint_file()

        if not checkpoint_file.exists():
            return None

        try:
            with open(checkpoint_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            return {
                'article_title': data.get('article_title'),
                'downloaded_count': len(data.get('downloaded_ids', [])),
                'checkpoint_file': str(checkpoint_file),
                'timestamp': data.get('timestamp'),
                'version': data.get('version')
            }

        except Exception:
            return None

    def list_checkpoints(self) -> List[Dict[str, Any]]:
        checkpoints = []

        for checkpoint_file in self.checkpoint_dir.glob('*.json'):
            if checkpoint_file.suffix == '.tmp':
                continue

            try:
                with open(checkpoint_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                checkpoints.append({
                    'article_title': data.get('article_title'),
                    'downloaded_count': len(data.get('downloaded_ids', [])),
                    'file': str(checkpoint_file),
                    'timestamp': data.get('timestamp'),
                    'version': data.get('version')
                })
            except Exception:
                continue

        return sorted(checkpoints, key=lambda x: x.get('timestamp', 0), reverse=True)

    def backup_checkpoint(self) -> Optional[Path]:
        checkpoint_file = self.get_checkpoint_file()

        if not checkpoint_file.exists():
            return None

        backup_file = self.checkpoint_dir / f"{self.article_title}.backup.json"

        try:
            import shutil
            shutil.copy2(checkpoint_file, backup_file)
            return backup_file
        except Exception as e:
            logger.warning(f"备份检查点失败: {e}")
            return None

    def restore_from_backup(self) -> bool:
        backup_file = self.checkpoint_dir / f"{self.article_title}.backup.json"
        checkpoint_file = self.get_checkpoint_file()

        if not backup_file.exists():
            return False

        try:
            import shutil
            shutil.copy2(backup_file, checkpoint_file)
            logger.info("已从备份恢复检查点")
            return True
        except Exception as e:
            logger.error(f"恢复检查点失败: {e}")
            return False
