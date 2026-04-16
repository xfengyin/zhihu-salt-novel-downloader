"""TXT文本导出器"""

import logging
from pathlib import Path
from typing import Dict, Any

from .base_exporter import BaseExporter


logger = logging.getLogger(__name__)


class TxtExporter(BaseExporter):
    """TXT文本导出器"""
    
    def export(self, article_info: Dict[str, Any]) -> Path:
        """
        导出为TXT文件
        
        Args:
            article_info: 文章信息字典
            
        Returns:
            输出文件路径
        """
        title = article_info.get('title', '未知标题')
        safe_title = self.sanitize_filename(title)
        output_path = self.output_dir / f"{safe_title}.txt"
        
        chapters = article_info.get('chapters', [])
        
        with open(output_path, 'w', encoding='utf-8') as f:
            # 写入标题
            f.write("=" * 60 + "\n")
            f.write(f"《{title}》\n")
            f.write("=" * 60 + "\n\n")
            
            # 写入元数据
            f.write(f"作者：{article_info.get('author', '未知')}\n")
            f.write(f"章节数：{len(chapters)}\n")
            f.write("\n" + "-" * 60 + "\n\n")
            
            # 按类型分组
            grouped = self.group_chapters(chapters)
            
            # 写入正文章节
            if grouped['normal']:
                f.write("【正文】\n\n")
                for i, chapter in enumerate(grouped['normal'], 1):
                    chapter_title = self.format_chapter_title(chapter, i)
                    content = chapter.get('content', '')
                    
                    f.write(f"{chapter_title}\n")
                    f.write("-" * 40 + "\n")
                    f.write(content)
                    f.write("\n\n")
            
            # 写入番外章节
            if grouped['extra']:
                f.write("\n\n" + "=" * 60 + "\n")
                f.write("【番外篇】\n\n")
                for chapter in grouped['extra']:
                    chapter_title = self.format_chapter_title(chapter, 0)
                    content = chapter.get('content', '')
                    
                    f.write(f"{chapter_title}\n")
                    f.write("-" * 40 + "\n")
                    f.write(content)
                    f.write("\n\n")
            
            # 写入作者说
            if grouped['author_note']:
                f.write("\n\n" + "=" * 60 + "\n")
                f.write("【作者说】\n\n")
                for chapter in grouped['author_note']:
                    chapter_title = self.format_chapter_title(chapter, 0)
                    content = chapter.get('content', '')
                    
                    f.write(f"{chapter_title}\n")
                    f.write("-" * 40 + "\n")
                    f.write(content)
                    f.write("\n\n")
            
            # 写入尾注
            f.write("\n" + "=" * 60 + "\n")
            f.write("【免责声明】\n")
            f.write("本电子书仅供已购买内容的个人离线阅读使用，\n")
            f.write("请勿用于任何形式的分发或商业用途。\n")
            f.write("=" * 60 + "\n")
        
        logger.info(f"TXT导出完成: {output_path}")
        return output_path
