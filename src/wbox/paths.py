"""wbox.paths —— 应用目录与运行环境（冻结态/开发态合一）。

硬规则（写死，不许绕）：
1. 应用数据（配置/工具/缓存/日志）只落在系统用户目录，不落在项目目录、
   不落在 exe 同级目录——保证"下载即用、卸载无痕"。
2. 冻结态（PyInstaller）与开发态走同一套 API：打包进去的只读资源经
   bundled_resource() 取，可写数据一律走 app_data_dir() 子树。
3. 所有路径返回 pathlib.Path，调用方自行 str()；跨平台分隔符由 Path 处理。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "WBox"
APP_DIR_NAME = "WBox"  # 数据目录名（%LOCALAPPDATA%/WBox）


def is_frozen() -> bool:
    """是否运行在 PyInstaller 冻结包里。"""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def bundled_root() -> Path:
    """只读资源根：冻结态为解包临时目录，开发态为仓库根。"""
    if is_frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[2]


def bundled_resource(*parts: str) -> Path:
    """取打包内置资源路径（如 apktool jar）。不存在时调用方自行报错。"""
    return bundled_root().joinpath(*parts)


def _windows_app_data() -> Path:
    local = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if local:
        return Path(local) / APP_DIR_NAME
    return Path.home() / "AppData" / "Local" / APP_DIR_NAME


def app_data_dir() -> Path:
    """应用可写数据根目录（不存在则创建）。"""
    if sys.platform.startswith("win"):
        base = _windows_app_data()
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")) / APP_DIR_NAME.lower()
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_path() -> Path:
    return app_data_dir() / "config.json"


def tools_dir() -> Path:
    p = app_data_dir() / "tools"
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir() -> Path:
    p = app_data_dir() / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def logs_dir() -> Path:
    p = app_data_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def clt_dir() -> Path:
    """Command Line Tools（hvigorw+SDK）安装目录。"""
    p = tools_dir() / "command-line-tools"
    p.mkdir(parents=True, exist_ok=True)
    return p


def apktool_jar_path() -> Path:
    """内置 apktool jar 的落地路径（首次使用时从包内解出）。"""
    return tools_dir() / "apktool.jar"


def jdk_dir() -> Path:
    p = tools_dir() / "jdk"
    p.mkdir(parents=True, exist_ok=True)
    return p
