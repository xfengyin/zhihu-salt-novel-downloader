"""断点续传测试"""

import pytest
import json
import time
from pathlib import Path
from utils.checkpoint import CheckpointManager


class TestCheckpointManager:
    """断点续传管理器测试"""

    @pytest.fixture
    def checkpoint_mgr(self, tmp_path):
        return CheckpointManager(str(tmp_path / "output"), "测试文章")

    def test_initialization(self, checkpoint_mgr):
        """测试初始化"""
        assert checkpoint_mgr.article_title == "测试文章"
        assert checkpoint_mgr.checkpoint_dir.exists()

    def test_save_and_load(self, checkpoint_mgr):
        """测试保存和加载"""
        downloaded_ids = {"chapter1", "chapter2", "chapter3"}

        checkpoint_mgr.save_checkpoint(downloaded_ids)

        loaded = checkpoint_mgr.load_checkpoint()

        assert loaded == downloaded_ids
        assert len(loaded) == 3

    def test_atomic_write(self, checkpoint_mgr, tmp_path):
        """测试原子写入"""
        downloaded_ids = {"chapter1", "chapter2"}

        checkpoint_mgr.save_checkpoint(downloaded_ids)

        checkpoint_file = checkpoint_mgr.get_checkpoint_file()
        assert checkpoint_file.exists()

        with open(checkpoint_file, 'r') as f:
            data = json.load(f)

        assert data['version'] == CheckpointManager.CHECKPOINT_VERSION
        assert data['downloaded_ids'] == sorted(list(downloaded_ids))
        assert 'timestamp' in data

    def test_empty_checkpoint(self, checkpoint_mgr):
        """测试空检查点"""
        loaded = checkpoint_mgr.load_checkpoint()
        assert loaded == set()

    def test_clear_checkpoint(self, checkpoint_mgr):
        """测试清除检查点"""
        checkpoint_mgr.save_checkpoint({"chapter1"})
        assert checkpoint_mgr.get_checkpoint_file().exists()

        checkpoint_mgr.clear_checkpoint()
        assert not checkpoint_mgr.get_checkpoint_file().exists()

    def test_get_progress(self, checkpoint_mgr):
        """测试获取进度"""
        checkpoint_mgr.save_checkpoint({"chapter1", "chapter2", "chapter3"})

        progress = checkpoint_mgr.get_progress()

        assert progress is not None
        assert progress['downloaded_count'] == 3
        assert progress['article_title'] == "测试文章"
        assert 'timestamp' in progress
        assert 'version' in progress

    def test_list_checkpoints(self, checkpoint_mgr, tmp_path):
        """测试列出检查点"""
        checkpoint_mgr.save_checkpoint({"chapter1"})

        checkpoint2 = CheckpointManager(str(tmp_path / "output"), "第二篇文章")
        checkpoint2.save_checkpoint({"chapter1", "chapter2"})

        checkpoints = checkpoint_mgr.list_checkpoints()

        assert len(checkpoints) == 2

    def test_backup_and_restore(self, checkpoint_mgr):
        """测试备份和恢复"""
        checkpoint_mgr.save_checkpoint({"chapter1", "chapter2"})

        backup = checkpoint_mgr.backup_checkpoint()
        assert backup is not None
        assert backup.exists()

        checkpoint_mgr.clear_checkpoint()
        assert not checkpoint_mgr.get_checkpoint_file().exists()

        restored = checkpoint_mgr.restore_from_backup()
        assert restored is True
        assert checkpoint_mgr.get_checkpoint_file().exists()

        loaded = checkpoint_mgr.load_checkpoint()
        assert loaded == {"chapter1", "chapter2"}

    def test_sorted_ids(self, checkpoint_mgr):
        """测试ID排序"""
        downloaded_ids = {"z", "a", "m"}

        checkpoint_mgr.save_checkpoint(downloaded_ids)

        with open(checkpoint_mgr.get_checkpoint_file(), 'r') as f:
            data = json.load(f)

        assert data['downloaded_ids'] == ['a', 'm', 'z']
