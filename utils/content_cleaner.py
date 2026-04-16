"""内容清洗器"""

import re
import logging
from typing import List, Pattern, Tuple


logger = logging.getLogger(__name__)


class ContentCleaner:
    """
    内容清洗器
    
    自动移除广告、水印、推广语等干扰内容
    """
    
    # 广告关键词
    AD_PATTERNS: List[Tuple[str, Pattern]] = [
        # 通用广告
        ('广告', re.compile(r'【?\s*广告\s*】?', re.I)),
        ('推广', re.compile(r'【?\s*推广\s*】?|本文.*推广|推广.*本文', re.I)),
        ('赞助', re.compile(r'【?\s*赞助\s*】?|感谢.*赞助', re.I)),
        ('投放', re.compile(r'【?\s*投放\s*】?|广告投放', re.I)),
        
        # 知乎特定
        ('盐选', re.compile(r'开通\s*盐选|加入\s*盐选|盐选会员', re.I)),
        ('会员', re.compile(r'立即\s*开通|开通\s*会员|会员专享', re.I)),
        
        # 电商推广
        ('淘宝', re.compile(r'淘宝.*?[0-9]{5,}|下单.*?[0-9]{5,}', re.I)),
        ('京东', re.compile(r'京东.*?[0-9]{5,}', re.I)),
        ('优惠券', re.compile(r'优惠券|券后|领券', re.I)),
        
        # 社交推广
        ('公众号', re.compile(r'公众号[:：]\s*\S+|搜索[:：]\s*\S+', re.I)),
        ('微信', re.compile(r'微[信号信码]+[:：]\s*\S+', re.I)),
        ('微博', re.compile(r'微博[:：]\s*\S+', re.I)),
        
        # 赞赏
        ('赞赏', re.compile(r'喜欢.*赞赏|觉得.*好.*赞赏|赞赏.*支持', re.I)),
    ]
    
    # 水印模式
    WATERMARK_PATTERNS: List[Pattern] = [
        re.compile(r'知乎.*?[@见]|@知乎用户', re.I),
        re.compile(r'未经.*授权|禁止.*转载', re.I),
        re.compile(r'首发于.*知乎', re.I),
    ]
    
    # 推广语模式
    PROMOTION_PATTERNS: List[Pattern] = [
        re.compile(r'点击.*?查看|点击.*?购买', re.I),
        re.compile(r'扫码.*?关注|长按.*?识别', re.I),
        re.compile(r'更多.*?请.*?|想.*?请.*?', re.I),
    ]
    
    # HTML标签清理
    HTML_TAG_PATTERN = re.compile(r'<[^>]+>')
    
    def __init__(self):
        self._enabled = True
    
    def clean(self, content: str) -> str:
        """
        清洗内容
        
        Args:
            content: 原始内容
            
        Returns:
            清洗后的内容
        """
        if not content or not self._enabled:
            return content
        
        # 移除HTML标签
        content = self.HTML_TAG_PATTERN.sub('', content)
        
        # 移除广告
        content = self._remove_ads(content)
        
        # 移除水印
        content = self._remove_watermarks(content)
        
        # 移除推广语
        content = self._remove_promotions(content)
        
        # 清理多余空白
        content = self._normalize_whitespace(content)
        
        return content
    
    def _remove_ads(self, content: str) -> str:
        """移除广告内容"""
        lines = content.split('\n')
        cleaned_lines = []
        skip_mode = False
        
        for line in lines:
            line_cleaned = line
            
            # 检查是否匹配广告模式
            is_ad = False
            for name, pattern in self.AD_PATTERNS:
                if pattern.search(line):
                    is_ad = True
                    logger.debug(f"移除广告: {name} - {line[:50]}...")
                    break
            
            if is_ad:
                continue
            
            # 检查是否整段都是广告
            stripped = line.strip()
            if len(stripped) < 20 and any(
                pattern.search(stripped) for _, pattern in self.AD_PATTERNS
            ):
                continue
            
            cleaned_lines.append(line)
        
        return '\n'.join(cleaned_lines)
    
    def _remove_watermarks(self, content: str) -> str:
        """移除水印"""
        for pattern in self.WATERMARK_PATTERNS:
            content = pattern.sub('', content)
        
        return content
    
    def _remove_promotions(self, content: str) -> str:
        """移除推广语"""
        for pattern in self.PROMOTION_PATTERNS:
            content = pattern.sub('', content)
        
        return content
    
    def _normalize_whitespace(self, content: str) -> str:
        """规范化空白"""
        # 移除行首行尾空白
        lines = [line.strip() for line in content.split('\n')]
        
        # 移除连续空行
        cleaned_lines = []
        prev_empty = False
        
        for line in lines:
            is_empty = not line
            
            if is_empty:
                if not prev_empty:
                    cleaned_lines.append('')
                prev_empty = True
            else:
                cleaned_lines.append(line)
                prev_empty = False
        
        return '\n'.join(cleaned_lines).strip()
    
    def add_ad_pattern(self, name: str, pattern: str):
        """
        添加广告匹配规则
        
        Args:
            name: 规则名称
            pattern: 正则表达式字符串
        """
        self.AD_PATTERNS.append((name, re.compile(pattern, re.I)))
    
    def add_watermark_pattern(self, pattern: str):
        """
        添加水印匹配规则
        
        Args:
            pattern: 正则表达式字符串
        """
        self.WATERMARK_PATTERNS.append(re.compile(pattern, re.I))
    
    def disable(self):
        """禁用清洗"""
        self._enabled = False
    
    def enable(self):
        """启用清洗"""
        self._enabled = True
