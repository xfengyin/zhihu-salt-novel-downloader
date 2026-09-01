"""书架模块（规格书 §2.13）：纯存储层，公共 API 重导出。

注意：本包只依赖 types/errors，**不 import engine**；
追更组合逻辑（check_new_chapters × shelf.list）在 CLI/server 层完成。
"""

from .shelf import DEFAULT_SHELF_FILE, Shelf, book_id_for

__all__ = ["DEFAULT_SHELF_FILE", "Shelf", "book_id_for"]

