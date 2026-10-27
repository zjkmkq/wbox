"""wbox.config —— 应用级设置持久化（最近工程/工具路径/AI 配置/界面）。

硬规则（写死，不许绕）：
1. 与工程级 spec.json 严格分层：本文件是"这台机器/这个用户"的设置，
   spec.json 是"这次迁移"的契约，互不读写。
2. 保存为原子写（临时文件 + os.replace），与 wbox.spec 同规格。
3. api_key 等敏感字段明文存放于用户本地目录（本应用为纯本地桌面软件，
   不上传任何数据）；不写入日志、不出现在任务包里。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wbox.paths import config_path

DEFAULTS: dict[str, Any] = {
    "recent_projects": [],  # [{path, name, opened_at}]，最新在前，最多 10 条
    "tools": {
        "java_home": "",            # 空=用 PATH 上的 java；可指到 JDK 根（含 bin/java.exe）
        "apktool_jar": "",          # 空=用内置/自动安装的 apktool.jar
        "command_line_tools": "",   # 空=用自动安装的；可指向已有解压目录
    },
    "ai": {
        "base_url": "",   # OpenAI 兼容端点，如 https://api.deepseek.com/v1
        "api_key": "",
        "model": "",
    },
    "ui": {
        "theme": "dark",   # dark=深色 IDE 风格（默认）/ light=浅色经典白；设置里可切
        # 旧版本默认是 light 但无主题切换；为不逆转用户既有的深色外观，
        # 只有用户在设置里显式选过主题（theme_chosen=True）才尊重 ui.theme。
        "theme_chosen": False,
        "window_size": [1480, 920],
        "last_step": "extract",
        # 帮助中心联网开关：true=本地知识库无结果时联网检索（内嵌浏览器）；
        # false=只查本地；未联网时联网区域自动隐藏（不占位、不报错）。
        "online_help": True,
    },
    # 工作区（2026-10-25 产品化）：所有拆解/工程/下载产物集中一棵目录树，
    # 默认 D:/WBoxWork（D 盘优先，C 盘空间常不足）；设置里可改、操作时可改。
    "workspace": {
        "root": "",      # 空=自动选（D:\\WBoxWork，无 D 盘则用户目录）
        "remember": True,
    },
    # 使用层级：pro=专业开发者（六步白盒工作台）；lite=普通用户（一键流水线）。
    "mode": "pro",
    # 运行行为：任务完成后自动关机（默认关，开启时完成前弹确认 + 60s 可取消倒计时）。
    "behavior": {
        "shutdown_on_finish": False,
        "avoid_delete": True,   # 删除一律进工作区 .wtrash/，不物理 unlink
    },
    # 文件系统恒英文命名（AI 解析友好）；此处只控制 UI 显示层：
    # zh=中文显示（默认，带开关），en=原文显示。
    "naming_display": "zh",
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    """读配置；文件不存在/损坏时返回默认值（不抛，保证应用能起来）。"""
    path = config_path()
    if not path.exists():
        return json.loads(json.dumps(DEFAULTS))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return json.loads(json.dumps(DEFAULTS))
    if not isinstance(data, dict):
        return json.loads(json.dumps(DEFAULTS))
    return _deep_merge(DEFAULTS, data)


def save(cfg: dict) -> None:
    """原子写配置。"""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def touch_recent_project(cfg: dict, project_path: str | Path, name: str = "") -> dict:
    """把工程置顶到最近列表（去重、截断到 10 条）。返回新 cfg（需调用方 save）。"""
    p = str(Path(project_path).resolve())
    items = [i for i in cfg.get("recent_projects", []) if i.get("path") != p]
    items.insert(0, {
        "path": p,
        "name": name or Path(p).name,
        "opened_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    cfg["recent_projects"] = items[:10]
    return cfg


def remove_recent_project(cfg: dict, project_path: str | Path) -> dict:
    p = str(Path(project_path).resolve())
    cfg["recent_projects"] = [i for i in cfg.get("recent_projects", []) if i.get("path") != p]
    return cfg


# ---------------------------------------------------------------- 工作区

def default_workspace_root() -> str:
    """工作区默认根：D 盘优先（用户明确 C 盘常满），无 D 盘退回用户目录。"""
    if sys.platform.startswith("win"):
        if Path("D:/").is_dir():
            return "D:/WBoxWork"
        return str(Path.home() / "WBoxWork")
    return str(Path.home() / "WBoxWork")


def workspace_root(cfg: dict) -> Path:
    """工作区根目录（不存在则创建；相对路径按 cwd 解析）。"""
    raw = str((cfg.get("workspace") or {}).get("root") or "").strip()
    root = Path(raw) if raw else Path(default_workspace_root())
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        root = Path(default_workspace_root())
        root.mkdir(parents=True, exist_ok=True)
    return root


def workspace_sub(cfg: dict, name: str) -> Path:
    """工作区子目录：projects / downloads / special / trash / cache / logs。

    - projects/   迁移工程（.wbox 工程目录）
    - downloads/  可下载资源（SDK/工具/APK 样本）
    - special/    拆解中的特殊资源（so/字体/未知格式待人工甄别）
    - trash/      .wtrash 软删除（avoid_delete=True 时的去处，可恢复）
    """
    p = workspace_root(cfg) / name
    p.mkdir(parents=True, exist_ok=True)
    return p
