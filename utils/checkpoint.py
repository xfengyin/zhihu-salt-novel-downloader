"""断点续传管理器"""

import json
import logging
from pathlib import Path
from typing import Set, Optional


logger = logging.getLogger(__name__)


class CheckpointManager:
    """
    断点续传管理器
    
    记录已下载章节ID，支持中断后继续下载
    """
    
    def __init__(self, output_dir: str, article_title: str):
        """
        初始化
        
        Args:
            output_dir: 输出目录
            article_title: 文章标题（用于生成文件名）
        """
        self.output_dir = Path(output_dir)
        self.article_title = self._sanitize_filename(article_title)
        self.checkpoint_dir = self.output_dir / '.checkpoints'
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
    
    def _sanitize_filename(self, filename: str) -> str:
        """清理文件名"""
        illegal_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
        for char in illegal_chars:
            filename = filename.replace(char, '_')
        return filename[:100]
    
    def get_checkpoint_file(self) -> Path:
        """获取检查点文件路径"""
        return self.checkpoint_dir / f"{self.article_title}.json"
    
    def save_checkpoint(self, downloaded_ids: Set[str]):
        """
        保存检查点
        
        Args:
            downloaded_ids: 已下载的章节ID集合
        """
        checkpoint_file = self.get_checkpoint_file()
        
        data = {
            'article_title': self.article_title,
            'downloaded_ids': list(downloaded_ids),
            'count': len(downloaded_ids)
        }
        
        with open(checkpoint_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.debug(f"检查点已保存: {len(downloaded_ids)} 个章节")
    
    def load_checkpoint(self) -> Set[str]:
        """
        加载检查点
        
        Returns:
            已下载的章节ID集合
        """
        checkpoint_file = self.get_checkpoint_file()
        
        if not checkpoint_file.exists():
            return set()
        
        try:
            with open(checkpoint_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            ids = set(data.get('downloaded_ids', []))
            logger.info(f"已加载检查点: {len(ids)} 个章节")
            return ids
            
        except Exception as e:
            logger.warning(f"加载检查点失败: {e}")
            return set()
    
    def clear_checkpoint(self):
        """清除检查点"""
        checkpoint_file = self.get_checkpoint_file()
        
        if checkpoint_file.exists():
            checkpoint_file.unlink()
            logger.info("检查点已清除")
    
    def get_progress(self) -> Optional[dict]:
        """
        获取下载进度
        
        Returns:
            进度信息字典
        """
        checkpoint_file = self.get_checkpoint_file()
        
        if not checkpoint_file.exists():
            return None
        
        try:
            with open(checkpoint_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            return {
                'article_title': data.get('article_title'),
                'downloaded_count': len(data.get('downloaded_ids', [])),
                'checkpoint_file': str(checkpoint_file)
            }
            
        except Exception:
            return None
    
    def list_checkpoints(self) -> list:
        """
        列出所有检查点
        
        Returns:
            检查点列表
        """
        checkpoints = []
        
        for checkpoint_file in self.checkpoint_dir.glob('*.json'):
            try:
                with open(checkpoint_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                checkpoints.append({
                    'article_title': data.get('article_title'),
                    'downloaded_count': len(data.get('downloaded_ids', [])),
                    'file': str(checkpoint_file)
                })
            except Exception:
                continue
        
        return checkpoints
