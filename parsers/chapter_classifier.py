"""智能章节分类器"""

import re
from enum import Enum
from typing import Dict, List, Pattern


class ChapterType(Enum):
    """章节类型"""
    NORMAL = 'normal'           # 正文
    EXTRA = 'extra'            # 番外
    AUTHOR_NOTE = 'author_note' # 作者说
    UNKNOWN = 'unknown'         # 其他


class ChapterClassifier:
    """
    智能章节分类器
    
    使用正则规则识别章节类型：
    - 正文：普通章节
    - 番外：番外篇、外传
    - 作者说：作者的话、作者说
    """
    
    # 番外关键词
    EXTRA_PATTERNS: List[Pattern] = [
        re.compile(r'番外', re.I),
        re.compile(r'外传', re.I),
        re.compile(r'特别篇', re.I),
        re.compile(r'extra', re.I),
        re.compile(r'side\s*story', re.I),
        re.compile(r'剧场版', re.I),
        re.compile(r'特典', re.I),
        re.compile(r'附录', re.I),
        re.compile(r'后日谈', re.I),
        re.compile(r'IF线', re.I),
    ]
    
    # 作者说关键词
    AUTHOR_NOTE_PATTERNS: List[Pattern] = [
        re.compile(r'作者说', re.I),
        re.compile(r'作者的话', re.I),
        re.compile(r'作者留言', re.I),
        re.compile(r'作者注', re.I),
        re.compile(r'作者前言', re.I),
        re.compile(r'作者后记', re.I),
        re.compile(r'作者小剧场', re.I),
        re.compile(r'作者小剧场', re.I),
        re.compile(r'彩蛋', re.I),
        re.compile(r'花絮', re.I),
    ]
    
    # 正文反例（排除项）
    EXCLUDE_PATTERNS: List[Pattern] = [
        re.compile(r'目录', re.I),
        re.compile(r'索引', re.I),
        re.compile(r'简介', re.I),
        re.compile(r'序章', re.I),
        re.compile(r'序幕', re.I),
        re.compile(r'楔子', re.I),
        re.compile(r'引子', re.I),
    ]
    
    def classify(self, title: str) -> ChapterType:
        """
        分类章节
        
        Args:
            title: 章节标题
            
        Returns:
            章节类型
        """
        if not title:
            return ChapterType.UNKNOWN
        
        # 优先检查作者说
        for pattern in self.AUTHOR_NOTE_PATTERNS:
            if pattern.search(title):
                return ChapterType.AUTHOR_NOTE
        
        # 检查番外
        for pattern in self.EXTRA_PATTERNS:
            if pattern.search(title):
                return ChapterType.EXTRA
        
        # 检查排除项
        for pattern in self.EXCLUDE_PATTERNS:
            if pattern.search(title):
                return ChapterType.UNKNOWN
        
        # 默认正文
        return ChapterType.NORMAL
    
    def classify_batch(self, titles: List[str]) -> Dict[str, ChapterType]:
        """
        批量分类
        
        Args:
            titles: 章节标题列表
            
        Returns:
            标题到类型的映射
        """
        return {title: self.classify(title) for title in titles}
    
    def get_type_label(self, chapter_type: ChapterType) -> str:
        """
        获取类型标签
        
        Args:
            chapter_type: 章节类型
            
        Returns:
            中文标签
        """
        labels = {
            ChapterType.NORMAL: '正文',
            ChapterType.EXTRA: '番外',
            ChapterType.AUTHOR_NOTE: '作者说',
            ChapterType.UNKNOWN: '其他'
        }
        return labels.get(chapter_type, '其他')
    
    def group_by_type(
        self,
        chapters: List[Dict]
    ) -> Dict[ChapterType, List[Dict]]:
        """
        按类型分组
        
        Args:
            chapters: 章节列表
            
        Returns:
            按类型分组的字典
        """
        grouped = {
            ChapterType.NORMAL: [],
            ChapterType.EXTRA: [],
            ChapterType.AUTHOR_NOTE: [],
            ChapterType.UNKNOWN: []
        }
        
        for chapter in chapters:
            ch_type = self.classify(chapter.get('title', ''))
            grouped[ch_type].append(chapter)
        
        return grouped
    
    def add_extra_pattern(self, pattern: str):
        """
        添加番外匹配规则
        
        Args:
            pattern: 正则表达式字符串
        """
        self.EXTRA_PATTERNS.append(re.compile(pattern, re.I))
    
    def add_author_note_pattern(self, pattern: str):
        """
        添加作者说匹配规则
        
        Args:
            pattern: 正则表达式字符串
        """
        self.AUTHOR_NOTE_PATTERNS.append(re.compile(pattern, re.I))
