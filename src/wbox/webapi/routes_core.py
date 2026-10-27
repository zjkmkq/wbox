"""wbox.webapi.routes_core —— 基础路由：工程 / spec / 文件 / 依赖 / 设置。

只放"快"路由（无长任务）；extract/assemble/build/ai 的流式路由在
routes_pipeline。所有 spec 读写经 webapi.core → wbox.spec 契约层。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Body, HTTPException

from wbox import config as app_config
from wbox import deps as dep_mod
from wbox.ascii_names import non_ascii_parts, work_dir_name
from wbox.spec import SPEC_VERSION
from wbox.webapi import core

router = APIRouter(prefix="/api", tags=["core"])


# ---------------------------------------------------------------- 依赖 / 设置

@router.get("/deps")
def api_deps() -> list[dict]:
    cfg = app_config.load()
    return [st.as_dict() for st in dep_mod.check_all(cfg)]


@router.get("/settings")
def api_get_settings() -> dict:
    cfg = app_config.load()
    ai = cfg.get("ai", {})
    key = str(ai.get("api_key", ""))
    return {
        "mode": cfg.get("mode", "pro"),
        "workspace_root": str(app_config.workspace_root(cfg)),
        "workspace_root_raw": str((cfg.get("workspace") or {}).get("root", "")),
        "behavior": cfg.get("behavior", {}),
        "naming_display": cfg.get("naming_display", "zh"),
        "tools": cfg.get("tools", {}),
        "ai": {**ai, "api_key": "", "api_key_set": bool(key)},  # key 不回传前端
    }


@router.put("/settings")
def api_put_settings(patch: dict = Body(default={})) -> dict:
    cfg = app_config.load()
    for key in ("mode", "naming_display"):
        if key in patch:
            cfg[key] = patch[key]
    for key in ("workspace", "behavior", "tools", "ai"):
        if key in patch and isinstance(patch[key], dict):
            cfg.setdefault(key, {}).update(patch[key])
    app_config.save(cfg)
    return api_get_settings()


# ---------------------------------------------------------------- 工程列表

@router.get("/projects")
def api_projects() -> dict:
    cfg = app_config.load()
    items = []
    for e in cfg.get("recent_projects", []):
        p = Path(str(e.get("path", "")))
        if (p / "spec.json").is_file():
            try:
                spec = core.load_spec(p)
                items.append(core.project_summary(p, spec))
            except HTTPException:
                continue
    # 工作区 projects/ 里不在最近列表的也补上（删了最近记录不丢工程）
    ws_projects = app_config.workspace_root(cfg) / "projects"
    known = {i["id"] for i in items}
    if ws_projects.is_dir():
        for d in sorted(ws_projects.iterdir()):
            if d.is_dir() and d.name not in known and (d / "spec.json").is_file():
                try:
                    items.append(core.project_summary(d, core.load_spec(d)))
                except HTTPException:
                    continue
    return {"projects": items, "workspace_root": str(app_config.workspace_root(cfg))}


@router.post("/projects")
def api_create_project(body: dict = Body(default={})) -> dict:
    """新建工程：{name, apk_path}。工程目录落工作区 projects/（ASCII 名）。"""
    apk = Path(str(body.get("apk_path", "")).strip())
    if not apk.is_file():
        raise HTTPException(400, f"APK 不存在：{apk}")
    cfg = app_config.load()
    pid = work_dir_name(apk.stem)
    target = app_config.workspace_sub(cfg, "projects") / (pid + ".wbox")
    if (target / "spec.json").is_file():
        raise HTTPException(409, f"工程已存在：{target.name}（请先打开或换个 APK）")
    try:
        core.create_project(target, apk, str(body.get("name") or apk.stem))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"新建失败：{e}") from e
    cfg = app_config.touch_recent_project(cfg, target, str(body.get("name") or apk.stem))
    app_config.save(cfg)
    return core.project_summary(target, core.load_spec(target))


@router.get("/projects/{pid}")
def api_project(pid: str) -> dict:
    cfg = app_config.load()
    pdir = core.resolve_project(pid, cfg)
    spec = core.load_spec(pdir)
    return {"project": core.project_summary(pdir, spec), "spec": spec,
            "spec_version": SPEC_VERSION}


@router.delete("/projects/{pid}/recent")
def api_forget_project(pid: str) -> dict:
    """只从最近列表移除（遵守 avoid_delete：不动工程文件）。"""
    cfg = app_config.load()
    pdir = core.resolve_project(pid, cfg)
    app_config.remove_recent_project(cfg, pdir)
    app_config.save(cfg)
    return {"ok": True}


@router.get("/projects/{pid}/ascii-check")
def api_ascii_check(pid: str) -> dict:
    cfg = app_config.load()
    pdir = core.resolve_project(pid, cfg)
    bad = non_ascii_parts(pdir)
    return {"ok": not bad, "bad_parts": [str(b) for b in bad]}


# ---------------------------------------------------------------- 文件浏览

@router.get("/projects/{pid}/files")
def api_files(pid: str, path: str = "") -> dict:
    cfg = app_config.load()
    pdir = core.resolve_project(pid, cfg)
    return {"path": path, "items": core.list_dir(pdir, path)}


@router.get("/projects/{pid}/file")
def api_file(pid: str, path: str) -> dict:
    cfg = app_config.load()
    pdir = core.resolve_project(pid, cfg)
    return core.read_text(pdir, path)


@router.get("/projects/{pid}/download")
def api_download(pid: str, path: str):
    """下载工程内文件（任务包等）：不在文本预览范围的也走这。"""
    from fastapi.responses import FileResponse
    cfg = app_config.load()
    pdir = core.resolve_project(pid, cfg)
    target = core.safe_child(pdir, path)
    if not target.is_file():
        raise HTTPException(404, f"文件不存在：{path}")
    return FileResponse(str(target), filename=target.name)
