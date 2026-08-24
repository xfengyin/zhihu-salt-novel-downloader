"""Web API - FastAPI + 静态文件，扫码登录与下载任务的极简后端。"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .client import ZhihuClient, ZhihuError

STATIC_DIR = Path(__file__).parent / "static"
OUTPUT_DIR = Path.home() / ".zhihu_downloader" / "output"

_executor = ThreadPoolExecutor(max_workers=4)
_tasks: dict[str, dict] = {}
_tasks_lock = threading.Lock()


class DownloadBody(BaseModel):
    """下载请求体。"""

    url: str
    format: str = "md"


def _run_download(client: ZhihuClient, task_id: str, url: str, fmt: str) -> None:
    """在后台线程执行下载并更新任务状态。"""
    with _tasks_lock:
        _tasks[task_id]["status"] = "running"

    try:
        result = client.download(url, fmt=fmt, output_dir=OUTPUT_DIR)
        files = [{"filename": Path(p).name, "path": str(p)} for p in result["files"]]
        with _tasks_lock:
            _tasks[task_id].update(
                {
                    "status": "success",
                    "title": result["title"],
                    "files": files,
                }
            )
    except Exception as e:  # noqa: BLE001 - 统一记录任务错误
        with _tasks_lock:
            _tasks[task_id]["status"] = "error"
            _tasks[task_id]["error"] = str(e)


def create_app(client: ZhihuClient | None = None) -> FastAPI:
    """创建 FastAPI 应用。``client`` 不传时使用默认（共享 Cookie 文件）。"""
    client = client or ZhihuClient()

    app = FastAPI(title="知乎盐选下载器 v4", version="4.3.0")

    # ------------------------------------------------------------------
    # 健康检查 / Cookie
    # ------------------------------------------------------------------

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/cookies")
    def cookies() -> dict:
        return {"has_cookie": bool(client.get_cookies())}

    # ------------------------------------------------------------------
    # 扫码登录
    # ------------------------------------------------------------------

    @app.post("/api/qrcode")
    def create_qrcode() -> dict:
        try:
            info = client.login_qr_start()
        except ZhihuError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        return {
            "token": info["token"],
            "image_url": f"/api/qrcode/{info['token']}/image",
        }

    @app.get("/api/qrcode/{token}/image")
    def qrcode_image(token: str) -> Response:
        try:
            image = client.login_qr_image(token)
        except ZhihuError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        return Response(content=image, media_type="image/jpeg")

    @app.get("/api/qrcode/{token}/status")
    def qrcode_status(token: str) -> dict:
        try:
            return client.login_qr_poll(token)
        except ZhihuError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

    # ------------------------------------------------------------------
    # 下载任务
    # ------------------------------------------------------------------

    @app.post("/api/download")
    def download(body: DownloadBody) -> dict:
        task_id = uuid.uuid4().hex
        with _tasks_lock:
            _tasks[task_id] = {
                "task_id": task_id,
                "url": body.url,
                "format": body.format,
                "status": "pending",
                "title": None,
                "files": [],
                "error": None,
            }
        _executor.submit(_run_download, client, task_id, body.url, body.format)
        return {"task_id": task_id}

    @app.get("/api/tasks")
    def list_tasks() -> list[dict]:
        with _tasks_lock:
            tasks = list(_tasks.values())
        return [
            {
                "task_id": t["task_id"],
                "url": t["url"],
                "status": t["status"],
                "title": t["title"],
                "error": t["error"],
            }
            for t in tasks
        ]

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str) -> dict:
        with _tasks_lock:
            task = _tasks.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return {
            "task_id": task["task_id"],
            "url": task["url"],
            "format": task["format"],
            "status": task["status"],
            "title": task["title"],
            "error": task["error"],
            "files": [f["filename"] for f in task["files"]],
        }

    @app.get("/api/files/{task_id}/{filename}")
    def get_file(task_id: str, filename: str) -> FileResponse:
        with _tasks_lock:
            task = _tasks.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        for f in task["files"]:
            if f["filename"] == filename:
                return FileResponse(f["path"], filename=filename)
        raise HTTPException(status_code=404, detail="文件不存在")

    # ------------------------------------------------------------------
    # 静态文件（frontend-dev 会填充 static/）
    # ------------------------------------------------------------------
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

    return app


app = create_app()
