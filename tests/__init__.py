"""pytest配置文件"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock


@pytest.fixture
def mock_response():
    """模拟HTTP响应"""
    response = MagicMock()
    response.status = 200
    response.text = AsyncMock(return_value='<html><body>Test Content</body></html>')
    return response


@pytest.fixture
def mock_aiohttp_session(mock_response):
    """模拟aiohttp会话"""
    session = MagicMock()
    session.get = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response)))
    return session


@pytest.fixture
def sample_article_info():
    """示例文章信息"""
    return {
        'title': '测试小说',
        'author': '测试作者',
        'url': 'https://www.zhihu.com/market/test',
        'chapters': [
            {
                'id': 'ch1',
                'title': '第一章 测试',
                'url': 'https://www.zhihu.com/answer/123',
                'type': 'normal',
                'content': '这是第一章的正文内容。\n\n包含多段落。'
            },
            {
                'id': 'ch2',
                'title': '番外篇 测试',
                'url': 'https://www.zhihu.com/answer/456',
                'type': 'extra',
                'content': '这是番外内容。'
            },
            {
                'id': 'ch3',
                'title': '作者说',
                'url': 'https://www.zhihu.com/answer/789',
                'type': 'author_note',
                'content': '作者想说的一些话。'
            }
        ]
    }


@pytest.fixture
def sample_html():
    """示例HTML内容"""
    return """
    <html>
        <head>
            <title>测试文章</title>
            <meta property="og:title" content="测试文章"/>
            <meta name="author" content="测试作者"/>
        </head>
        <body>
            <div class="article-content">
                <h1>测试标题</h1>
                <p>第一段内容。</p>
                <p>第二段内容。</p>
            </div>
            <div class="toc">
                <a href="/answer/123">第一章</a>
                <a href="/answer/456">第二章</a>
            </div>
        </body>
    </html>
    """


@pytest.fixture
def sample_cookies():
    """示例Cookie"""
    return {
        'z_c0': 'test_token_value',
        'q_c1': 'test_qc1',
        'tgw_l7_route': 'test_route'
    }
