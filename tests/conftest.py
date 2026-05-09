"""pytest配置和共享fixtures"""

import pytest
from pathlib import Path


@pytest.fixture
def sample_article_info():
    """示例文章信息"""
    return {
        'title': '测试小说',
        'author': '测试作者',
        'url': 'https://www.zhihu.com/question/123456',
        'chapters': [
            {
                'id': '1',
                'title': '第一章：开始',
                'url': 'https://www.zhihu.com/answer/1',
                'order': 1,
                'type': 'normal',
                'content': '这是第一章的内容。'
            },
            {
                'id': '2',
                'title': '第二章：发展',
                'url': 'https://www.zhihu.com/answer/2',
                'order': 2,
                'type': 'normal',
                'content': '这是第二章的内容。'
            },
            {
                'id': '3',
                'title': '番外：特别篇',
                'url': 'https://www.zhihu.com/answer/3',
                'order': 3,
                'type': 'extra',
                'content': '这是番外内容。'
            },
            {
                'id': '4',
                'title': '作者说',
                'url': 'https://www.zhihu.com/answer/4',
                'order': 4,
                'type': 'author_note',
                'content': '这是作者的话。'
            }
        ],
        'chapter_count': 4
    }


@pytest.fixture
def sample_html():
    """示例HTML内容"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>测试小说 - 知乎</title>
        <meta property="og:title" content="测试小说">
        <meta name="author" content="测试作者">
    </head>
    <body>
        <h1>测试小说</h1>
        <div class="RichText">
            <p>这是测试内容。</p>
        </div>
        <ul class="toc">
            <li class="toc-item"><a href="/answer/1">第一章</a></li>
            <li class="toc-item"><a href="/answer/2">第二章</a></li>
        </ul>
    </body>
    </html>
    """


@pytest.fixture
def parser():
    """文章解析器实例"""
    from parsers.article_parser import ArticleParser
    return ArticleParser()
