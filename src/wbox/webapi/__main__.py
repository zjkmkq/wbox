"""python -m wbox.webapi —— 启动 WBox Web API 服务。

用法：
    python -m wbox.webapi                    # 127.0.0.1:8580，无静态托管
    python -m wbox.webapi --port 8580 --dist D:/Game/GC/code/dist
                                               # 单端口完整产品（API + 前端）

设计：uvicorn 单 worker（本地工具，长任务在 daemon 线程里跑，不走进程池）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wbox-webapi", description="WBox Web API 服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8580)
    parser.add_argument("--dist", default="",
                        help="前端构建产物目录（含 index.html）；给了即单端口托管")
    args = parser.parse_args(argv)

    # dist 目录通过环境变量传给 app 工厂（uvicorn 以字符串导入 app 对象）
    dist = args.dist
    if dist and not (Path(dist) / "index.html").is_file():
        print(f"[wbox-webapi] 警告：{dist} 里没有 index.html，跳过静态托管", file=sys.stderr)
        dist = ""
    import os
    os.environ["WBOX_WEB_DIST"] = dist

    uvicorn.run(
        "wbox.webapi.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
