"""wbox.webapi 包：Web API 层（FastAPI）。

入口：python -m wbox.webapi [--port 8580] [--dist 前端dist目录]
"""

from __future__ import annotations

from wbox.webapi.app import create_app

__all__ = ["create_app"]
