"""app 包：本地 Web 服务（规格书 §2.14）。

公共 API 只有一个 create_app 工厂（模块级不放 app 实例——v4 教训：
import 即实例化会连带副作用；uvicorn 用 --factory 启动）。
静态 UI 由 I2 负责，见 static/。
"""

from .server import create_app

__all__ = ["create_app"]
