"""导出器基类"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime


class BaseExporter(ABC):
    """导出器基类"""
    
    def __init__(self, output_dir: Path):
        """
        初始化导出器
        
        Args:
            output_dir: 输出目录
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    @abstractmethod
    def export(self, article_info: Dict[str, Any]) -> Path:
        """
        导出文件
        
        Args:
            article_info: 文章信息字典
            
        Returns:
            输出文件路径
        """
        pass
    
    def sanitize_filename(self, filename: str) -> str:
        """
        清理文件名
        
        Args:
            filename: 原始文件名
            
        Returns:
            清理后的文件名
        """
        # 替换非法字符
        illegal_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
        for char in illegal_chars:
            filename = filename.replace(char, '_')
        
        # 限制长度
        if len(filename) > 200:
            filename = filename[:200]
        
        return filename.strip()
    
    def group_chapters(self, chapters: List[Dict]) -> Dict[str, List[Dict]]:
        """
        按类型分组章节
        
        Args:
            chapters: 章节列表
            
        Returns:
            分组后的字典
        """
        grouped = {
            'normal': [],
            'extra': [],
            'author_note': []
        }
        
        for ch in chapters:
            ch_type = ch.get('type', 'normal')
            if ch_type in grouped:
                grouped[ch_type].append(ch)
            else:
                grouped['normal'].append(ch)
        
        return grouped
    
    def format_chapter_title(self, chapter: Dict, index: int) -> str:
        """
        格式化章节标题
        
        Args:
            chapter: 章节信息
            index: 章节序号
            
        Returns:
            格式化后的标题
        """
        title = chapter.get('title', f'第{index}章')
        ch_type = chapter.get('type', 'normal')
        
        type_prefix = {
            'normal': '',
            'extra': '【番外】',
            'author_note': '【作者说】'
        }.get(ch_type, '')
        
        return f"{type_prefix}{title}"
    
    def build_metadata(self, article_info: Dict[str, Any]) -> Dict[str, str]:
        """
        构建元数据
        
        Args:
            article_info: 文章信息
            
        Returns:
            元数据字典
        """
        return {
            'title': article_info.get('title', '未知标题'),
            'author': article_info.get('author', '未知作者'),
            'created': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'chapter_count': str(len(article_info.get('chapters', []))),
            'source': article_info.get('url', '')
        }
