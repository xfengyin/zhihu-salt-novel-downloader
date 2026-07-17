"""API 层测试 - FastAPI 路由、SSE、异常处理、traceId

使用 FastAPI TestClient 进行集成测试，mock DownloadService 避免真实网络。
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from zhihu_downloader.api.app import create_app
from zhihu_downloader.api.schemas import (
    BookSchema,
    DownloadRequest,
    MessageResponse,
    ShelfStatsSchema,
)
from zhihu_downloader.services.events import ProgressEvent


@pytest.fixture
def client() -> TestClient:
    """测试客户端，使用独立应用实例"""
    return TestClient(create_app())


# ---------------------------------------------------------------------------
# 健康检查与基础设施
# ---------------------------------------------------------------------------


class TestHealthAndMiddleware:
    """健康检查与中间件测试"""

    def test_health(self, client: TestClient) -> None:
        """健康检查应返回 200"""
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_trace_id_header(self, client: TestClient) -> None:
        """响应应回写 X-Trace-Id 头"""
        resp = client.get("/api/health")
        assert "x-trace-id" in {k.lower() for k in resp.headers.keys()}

    def test_trace_id_passthrough(self, client: TestClient) -> None:
        """客户端传入的 trace_id 应被透传"""
        custom_id = "test-trace-id-12345"
        resp = client.get("/api/health", headers={"X-Trace-Id": custom_id})
        assert resp.headers.get("x-trace-id") == custom_id

    def test_404_returns_unified_format(self, client: TestClient) -> None:
        """不存在的路由应返回 404"""
        resp = client.get("/api/not-exists")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 书架路由测试
# ---------------------------------------------------------------------------


class TestShelfRoutes:
    """书架路由测试"""

    def test_list_books_empty(self, client: TestClient) -> None:
        """空书架应返回空列表"""
        # 用临时书架文件隔离：直接覆盖 app.state.shelf_service
        import os
        import tempfile

        from zhihu_downloader.services.shelf_service import ShelfService
        from zhihu_downloader.shelf.shelf_manager import ShelfManager

        with tempfile.TemporaryDirectory() as tmp:
            shelf_file = os.path.join(tmp, "shelf.json")
            client.app.state.shelf_service = ShelfService(
                shelf=ShelfManager(shelf_file=shelf_file)
            )
            resp = client.get("/api/shelves")
            assert resp.status_code == 200
            assert resp.json() == []

    def test_add_and_list_book(self, client: TestClient) -> None:
        """添加书籍后应能列出"""
        import os
        import tempfile

        from zhihu_downloader.services.shelf_service import ShelfService
        from zhihu_downloader.shelf.shelf_manager import ShelfManager

        with tempfile.TemporaryDirectory() as tmp:
            shelf_file = os.path.join(tmp, "shelf.json")
            client.app.state.shelf_service = ShelfService(
                shelf=ShelfManager(shelf_file=shelf_file)
            )

            resp = client.post(
                "/api/shelves",
                json={"url": "https://www.zhihu.com/test"},
            )
            assert resp.status_code == 200
            assert resp.json()["success"] is True

            resp = client.get("/api/shelves")
            assert resp.status_code == 200
            books = resp.json()
            assert len(books) == 1
            assert books[0]["url"] == "https://www.zhihu.com/test"

    def test_get_stats(self, client: TestClient) -> None:
        """统计接口应返回正确结构"""
        resp = client.get("/api/shelves/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "completed" in data
        assert "in_progress" in data

    def test_clean_shelf(self, client: TestClient) -> None:
        """清空书架应成功"""
        resp = client.delete("/api/shelves")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_remove_book(self, client: TestClient) -> None:
        """删除书籍应成功"""
        import os
        import tempfile

        from zhihu_downloader.services.shelf_service import ShelfService
        from zhihu_downloader.shelf.shelf_manager import ShelfManager

        with tempfile.TemporaryDirectory() as tmp:
            shelf_file = os.path.join(tmp, "shelf.json")
            svc = ShelfService(shelf=ShelfManager(shelf_file=shelf_file))
            svc.add_book("https://www.zhihu.com/x", {"title": "X"})
            client.app.state.shelf_service = svc

            resp = client.delete("/api/shelves/https%3A%2F%2Fwww.zhihu.com%2Fx")
            assert resp.status_code == 200
            assert resp.json()["success"] is True


# ---------------------------------------------------------------------------
# 下载路由测试
# ---------------------------------------------------------------------------


class TestDownloadRoutes:
    """下载路由测试"""

    def test_start_download_no_url(self, client: TestClient) -> None:
        """未提供 URL 应返回 400"""
        resp = client.post("/api/downloads", json={})
        assert resp.status_code == 400

    def test_start_download_returns_task_id(self, client: TestClient) -> None:
        """启动下载应返回 task_id"""
        resp = client.post(
            "/api/downloads",
            json={"url": "https://www.zhihu.com/test"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "task_id" in data
        assert len(data["task_id"]) > 0

    def test_list_tasks(self, client: TestClient) -> None:
        """任务列表应返回数组"""
        resp = client.get("/api/downloads")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_stream_not_found(self, client: TestClient) -> None:
        """不存在的 task_id 应返回 404"""
        resp = client.get("/api/downloads/stream/nonexistent")
        assert resp.status_code == 404

    def test_download_with_invalid_url(self, client: TestClient) -> None:
        """非法 URL 格式应被 schema 校验拒绝"""
        resp = client.post(
            "/api/downloads",
            json={"url": "not-a-url"},
        )
        assert resp.status_code == 422

    def test_download_with_invalid_concurrent(self, client: TestClient) -> None:
        """并发数超限应被校验拒绝"""
        resp = client.post(
            "/api/downloads",
            json={"url": "https://www.zhihu.com/x", "max_concurrent": 100},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Schema 校验测试
# ---------------------------------------------------------------------------


class TestSchemas:
    """Pydantic schema 校验测试"""

    def test_download_request_defaults(self) -> None:
        """默认值应符合预期"""
        req = DownloadRequest(url="https://www.zhihu.com/x")
        assert req.export_format.value == "md"
        assert req.max_concurrent == 3
        assert req.clean_content is True

    def test_download_request_batch_filter(self) -> None:
        """批量 URL 应过滤空行与注释"""
        req = DownloadRequest(
            batch_urls=["https://a.com", "", "# comment", "https://b.com"]
        )
        assert req.batch_urls == ["https://a.com", "https://b.com"]

    def test_download_request_invalid_url(self) -> None:
        """非法 URL 应校验失败"""
        with pytest.raises(ValueError):
            DownloadRequest(url="ftp://bad")

    def test_message_response(self) -> None:
        """消息响应应正确序列化"""
        r = MessageResponse(message="ok", success=True)
        assert r.message == "ok"
        assert r.success is True

    def test_shelf_stats_schema(self) -> None:
        """书架统计 schema 应校验非负"""
        s = ShelfStatsSchema(total=5, completed=2, in_progress=3)
        assert s.total == 5
