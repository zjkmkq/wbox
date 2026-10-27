"""wbox.webapi —— WBox 的 Web API 层：把 Python 核心包成 HTTP 服务。

定位（写死）：
- 服务端零 Qt 依赖（GUI 是另一个前端；Web 前端与 PySide6 共用同一核心）。
- spec 只经 wbox.spec 契约层读写（经 webapi.core）。
- 长任务（拆/装配/编译/AI 生成）走 SSE；快操作走 JSON。
- 静态托管：dist/ 存在时挂到 /，单端口即完整产品；开发态由 vite 代理 /api。
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from wbox.webapi.routes_core import router as core_router
from wbox.webapi.routes_pipeline import router as pipeline_router

API_DESCRIPTION = """\
WBox 跨平台迁移白盒工作台的 Web API。六步流水线：
① 拆（extract，SSE）② 画拼图（proposal）③ 判断（decisions）
④ 填上（taskpack / draft 粘贴导入 / ai 生成 SSE）⑤ 装配（assemble）⑥ 补缝（build SSE）。
所有迁移数据经 spec.json 契约层（wbox.spec）读写。
"""


def create_app(static_dir: str | Path | None = None) -> FastAPI:
    app = FastAPI(
        title="WBox Web API",
        version="0.2.0",
        description=API_DESCRIPTION,
    )
    # 开发态 vite dev server（5199 等）跨源调 API；生产同源无此必要但无害
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],          # 纯本地工具，无凭证外泄面；key 从不经前端
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(core_router)
    app.include_router(pipeline_router)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "name": "wbox-webapi", "version": "0.2.0"}

    # 静态托管（单端口交付）：显式参数 > 环境变量 WBOX_WEB_DIST；有 index.html 才挂。
    # 不用 StaticFiles(html=True)：它的 fallback 依赖 Accept: text/html，
    # 对无浏览器头的客户端（嵌入式 webview / 探针）深链会 404。
    # 改为显式 catch-all：真实文件直出，其余（含 /workspace/<pid> 深链）回 index.html。
    if not static_dir:
        static_dir = os.environ.get("WBOX_WEB_DIST", "")
    if static_dir:
        dist = Path(static_dir).resolve()
        index_html = dist / "index.html"
        if index_html.is_file():
            @app.get("/{full_path:path}", include_in_schema=False)
            def spa_fallback(full_path: str):
                if full_path.startswith("api/"):
                    # API 命名空间的 404 保持 JSON 形状，不被 SPA fallback 吞掉
                    raise HTTPException(status_code=404, detail="Not Found")
                if full_path:
                    candidate = (dist / full_path).resolve()
                    # 防穿越：candidate 必须仍在 dist 内
                    try:
                        candidate.relative_to(dist)
                    except ValueError:
                        return FileResponse(index_html)
                    if candidate.is_file():
                        return FileResponse(candidate)
                return FileResponse(index_html)
    return app
