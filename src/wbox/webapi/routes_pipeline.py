"""wbox.webapi.routes_pipeline —— 流水线路由：拆/提案/决策/填/补缝 + AI 直连。

长任务（extract / assemble / build / ai 生成）全部走 SSE：
    POST /api/projects/{pid}/extract   → text/event-stream
    POST /api/projects/{pid}/assemble  → text/event-stream
    POST /api/projects/{pid}/build     → text/event-stream
    POST /api/ai/generate              → text/event-stream
快操作（提案/决策/任务包/粘贴导入/缝状态）走普通 JSON。

并发守卫：同一工程同时只允许一个 extract / build（_LOCKS 字典 + 409）。
"""

from __future__ import annotations

import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import StreamingResponse

from wbox import aiclient
from wbox import config as app_config
from wbox import deps as dep_mod
from wbox import hvigor
from wbox import taskpack
from wbox.assemble import assemble_project
from wbox.draft import apply_draft, draft_summary
from wbox.extract import build_spec, merge_manual_records
from wbox.plan import generate_proposal
from wbox.spec import load
from wbox.webapi import core
from wbox.webapi.streams import LogBus, run_worker

router = APIRouter(prefix="/api", tags=["pipeline"])

# 并发守卫：{("extract"|"build", pid): True}；线程内 finally 清理
_LOCKS: dict[tuple[str, str], bool] = {}
_LOCK_GUARD = threading.Lock()


def _acquire(kind: str, pid: str) -> None:
    with _LOCK_GUARD:
        if _LOCKS.get((kind, pid)):
            raise HTTPException(409, f"该工程已有进行中的{kind}任务，请勿重复启动")
        _LOCKS[(kind, pid)] = True


def _release(kind: str, pid: str) -> None:
    with _LOCK_GUARD:
        _LOCKS.pop((kind, pid), None)


def _module_id(spec: dict) -> str:
    mods = spec.get("modules", [])
    if mods and isinstance(mods[0], dict) and mods[0].get("id"):
        return str(mods[0]["id"])
    return "mod_001"


# ---------------------------------------------------------------- ① 拆（SSE）

def _extract_worker(bus: LogBus, pdir: Path, apk: Path, force: bool) -> None:
    cfg = app_config.load()
    java = dep_mod.java_bin(cfg)
    jar = dep_mod.apktool_jar(cfg)
    work = pdir / "work" / apk.stem
    bus.put_step("apktool 解包")
    bus.put_log(f"{java} -jar {jar} d {apk.name} -o {work}")
    proc = subprocess.Popen([java, "-jar", jar, "d", str(apk), "-o", str(work), "-f"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, errors="replace", bufsize=1)
    assert proc.stdout is not None
    for line in proc.stdout:
        bus.put_log(line)
    code = proc.wait()
    if code != 0:
        bus.put_error(f"apktool 解包失败（退出码 {code}）")
        return
    if not (work / "AndroidManifest.xml").exists():
        bus.put_error(f"解包目录不完整（缺 AndroidManifest.xml）：{work}")
        return
    bus.put_step("解析资源与代码骨架")
    try:
        new_spec = build_spec(apk, work)
        spec_file = pdir / "spec.json"
        if spec_file.exists():
            if not force:
                bus.put_error("spec 已存在；重复提取请携带 force=true"
                              "（decisions/seams 会保留，build_log 追加不清空）")
                return
            new_spec = merge_manual_records(new_spec, load(spec_file))
        core.save_spec(pdir, new_spec)
    except Exception as e:  # noqa: BLE001  流式通道一切失败显式上报
        bus.put_error(f"解析失败：{e}")
        return
    counts = (f"资源 {len(new_spec.get('resources', []))} / "
              f"模块 {len(new_spec.get('modules', []))} / "
              f"行为 {len(new_spec.get('behaviors', []))}")
    bus.put_done(True, f"拆解完成：{counts}",
                 extra={"counts": {"resources": len(new_spec.get("resources", [])),
                                   "modules": len(new_spec.get("modules", [])),
                                   "behaviors": len(new_spec.get("behaviors", []))}})


@router.post("/projects/{pid}/extract")
def api_extract(pid: str, body: dict = Body(default={})) -> StreamingResponse:
    cfg = app_config.load()
    pdir = core.resolve_project(pid, cfg)
    spec = core.load_spec(pdir)
    apk = Path(str(spec.get("project", {}).get("source", "")))
    if not apk.is_file():
        apk = Path(str(body.get("apk_path", "")))
    if not apk.is_file():
        raise HTTPException(400, "找不到 APK：工程 spec 未记录来源，且本次未提供 apk_path")
    _acquire("extract", pid)
    bus = LogBus()

    def _run(b: LogBus) -> None:
        try:
            _extract_worker(b, pdir, apk, bool(body.get("force", False)))
        finally:
            _release("extract", pid)

    run_worker(bus, _run)
    return StreamingResponse(bus.events(), media_type="text/event-stream")


# ---------------------------------------------------------------- ② 提案

@router.post("/projects/{pid}/proposal")
def api_proposal(pid: str, write: bool = False) -> dict:
    cfg = app_config.load()
    pdir = core.resolve_project(pid, cfg)
    spec = core.load_spec(pdir)
    proposal = generate_proposal(spec)
    if write:
        spec["proposal"] = proposal
        core.save_spec(pdir, spec)
    return {"proposal": proposal}


@router.put("/projects/{pid}/resources/{rid}")
def api_update_resource(pid: str, rid: str, body: dict = Body(default={})) -> dict:
    cfg = app_config.load()
    pdir = core.resolve_project(pid, cfg)
    spec = core.load_spec(pdir)
    for r in spec.get("resources", []):
        if str(r.get("id")) == rid:
            if "action" in body:
                r["action"] = body["action"]
            if "target" in body:
                r["target"] = body["target"]
            core.save_spec(pdir, spec)
            return {"ok": True, "item": r}
    raise HTTPException(404, f"资源不存在：{rid}")


@router.put("/projects/{pid}/modules/{mid}")
def api_update_module(pid: str, mid: str, body: dict = Body(default={})) -> dict:
    cfg = app_config.load()
    pdir = core.resolve_project(pid, cfg)
    spec = core.load_spec(pdir)
    for m in spec.get("modules", []):
        if str(m.get("id")) == mid:
            if "action" in body:
                m["action"] = body["action"]
            if "target" in body:
                m["target"] = body["target"]
            core.save_spec(pdir, spec)
            return {"ok": True, "item": m}
    raise HTTPException(404, f"模块不存在：{mid}")


# ---------------------------------------------------------------- ③ 决策

@router.post("/projects/{pid}/decisions")
def api_add_decision(pid: str, body: dict = Body(default={})) -> dict:
    """记录人工裁决。字段与 spec schema 的 decision 定义严格对齐：
    id(dec_NNN) / topic / chosen / reason / decided_by=human / decided_at。
    前端传 issueTitle→topic、conclusion→chosen（兼容旧字段名）。
    """
    cfg = app_config.load()
    pdir = core.resolve_project(pid, cfg)
    spec = core.load_spec(pdir)
    session = core.SpecSession(pdir, spec)
    topic = str(body.get("topic") or body.get("issueTitle") or "").strip()
    chosen = str(body.get("chosen") or body.get("conclusion") or "").strip()
    if not topic or not chosen:
        raise HTTPException(400, "topic（问题主题）与 chosen（结论）都不能为空")
    spec.setdefault("decisions", []).append({
        "id": session.next_id("decisions", "dec_"),
        "topic": topic,
        "chosen": chosen,
        "reason": str(body.get("reason", "")),
        "decided_by": "human",
        "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    session.save("记录决策")
    return {"ok": True, "decisions": spec["decisions"]}


# ---------------------------------------------------------------- ④ 填上

@router.post("/projects/{pid}/taskpack")
def api_taskpack(pid: str) -> dict:
    cfg = app_config.load()
    pdir = core.resolve_project(pid, cfg)
    out = pdir / "exports"
    try:
        pack_dir = taskpack.build_taskpack(pdir / "spec.json", out)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"任务包导出失败：{e}") from e
    # Web 端下载目录不便：stdlib zipfile 打成单文件（无第三方依赖）。
    # 铁律（2026-10-25 实测踩坑）：zip 绝不允许写在被打包目录内——
    # rglob 懒遍历会把正在写的 zip 自己也吞进去，自引用无限增长
    # （实测 4 分钟涨到 9GB 挂死请求）。tmp 落工程根，写完原子移入。
    import os
    import zipfile
    from datetime import datetime
    pack_files = [f.name for f in sorted(pack_dir.iterdir()) if f.is_file()]  # 先快照再打包
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    tmp = pdir / f".taskpack-{stamp}.tmp"
    zip_path = out / f"taskpack-{stamp}.zip"
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(pack_dir.rglob("*")):
                if f.is_file() and f.suffix.lower() != ".zip":
                    zf.write(f, f.relative_to(pack_dir.parent).as_posix())
        os.replace(tmp, zip_path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    rel = zip_path.relative_to(pdir).as_posix()
    return {"ok": True,
            "path": rel,
            "download": f"/api/projects/{pid}/download?path={rel}",
            "files": pack_files}


@router.post("/projects/{pid}/draft")
def api_draft_import(pid: str, body: dict = Body(default={})) -> dict:
    cfg = app_config.load()
    pdir = core.resolve_project(pid, cfg)
    text = str(body.get("text", ""))
    if not text.strip():
        raise HTTPException(400, "粘贴内容为空")
    result = apply_draft(text, pdir / "draft")
    if not result.written and not result.skipped:
        raise HTTPException(400, "没有解析到 FILE 段（格式：// FILE: 相对路径 + 代码块）")
    spec = core.load_spec(pdir)
    session = core.SpecSession(pdir, spec)
    spec.setdefault("build_log", []).append({
        "id": session.next_id("build_log", "log_"),
        "module_id": _module_id(spec),
        "action": "draft_generated",
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": f"粘贴导入 {len(result.written)} 个文件（跳过 {len(result.skipped)}）",
        "diff_ref": "draft/",
    })
    session.save("粘贴导入")
    return {"ok": True, "summary": draft_summary(result),
            "written": result.written, "skipped": result.skipped}


# ---------------------------------------------------------------- AI 直连（SSE）

def _ai_worker(bus: LogBus, pdir: Path, prompt: str) -> None:
    cfg = app_config.load()
    client = aiclient.client_from_config(cfg)
    if not client.configured:
        bus.put_error("AI 未配置：请在设置里填 base_url / api_key / model")
        return
    spec = core.load_spec(pdir)
    full_prompt = prompt or taskpack.render_prompt(spec, [])
    chunks: list[str] = []

    def _on_delta(text: str) -> None:
        chunks.append(text)
        bus.put_log(text)

    result = client.chat_stream(full_prompt, system=_METHODOLOGY_HINT, on_delta=_on_delta)
    if not result.ok:
        bus.put_error(result.error)
        return
    bus.put_done(True, f"生成 {len(''.join(chunks))} 字符",
                 extra={"content": "".join(chunks)})


_METHODOLOGY_HINT = (
    "你是 HarmonyOS NEXT 迁移专家。输出标准 FILE 格式："
    "每个文件以 // FILE: 相对路径 开头，后跟 ```ets 代码块。"
    "只输出代码，不要解释。"
)


@router.post("/ai/generate")
def api_ai_generate(body: dict = Body(default={})) -> StreamingResponse:
    pid = str(body.get("pid", ""))
    cfg = app_config.load()
    pdir = core.resolve_project(pid, cfg) if pid else None
    if pdir is None:
        raise HTTPException(400, "缺少 pid（AI 生成需要工程上下文）")
    bus = LogBus()
    run_worker(bus, _ai_worker, pdir, str(body.get("prompt", "")))
    return StreamingResponse(bus.events(), media_type="text/event-stream")


# ---------------------------------------------------------------- ⑥ 补缝

def _assemble_worker(bus: LogBus, pdir: Path) -> None:
    result = assemble_project(pdir / "spec.json", on_log=bus.put_log)
    if result.ok:
        bus.put_done(True, f"装配完成：{result.project_dir}",
                     extra={"project_dir": str(result.project_dir)})
    else:
        bus.put_error(result.error or "装配失败")


@router.post("/projects/{pid}/assemble")
def api_assemble(pid: str) -> StreamingResponse:
    cfg = app_config.load()
    pdir = core.resolve_project(pid, cfg)
    bus = LogBus()
    run_worker(bus, _assemble_worker, pdir)
    return StreamingResponse(bus.events(), media_type="text/event-stream")


def _build_worker(bus: LogBus, pdir: Path, project_dir: Path) -> None:
    result = hvigor.run_build(project_dir, on_line=bus.put_log, cfg=app_config.load())
    spec = core.load_spec(pdir)
    session = core.SpecSession(pdir, spec)
    hvigor.append_build_log(session, _module_id(spec), result)
    if result.ok:
        bus.put_done(True, result.summary, extra={"hap_path": result.hap_path})
    else:
        bus.put_error(result.error or "编译失败")


@router.post("/projects/{pid}/build")
def api_build(pid: str, body: dict = Body(default={})) -> StreamingResponse:
    cfg = app_config.load()
    pdir = core.resolve_project(pid, cfg)
    project = Path(str(body.get("harmony_dir", "")).strip())
    if not project.is_dir():
        # 与 GUI seal_step 同策略：工程附近探测真实鸿蒙工程
        project = _probe_harmony_dir(pdir) or Path("")
    if not (project / "build-profile.json5").is_file():
        raise HTTPException(400, f"不是鸿蒙工程目录（缺 build-profile.json5）：{project or '（未找到）'}")
    _acquire("build", pid)
    bus = LogBus()

    def _run(b: LogBus) -> None:
        try:
            _build_worker(b, pdir, project)
        finally:
            _release("build", pid)

    run_worker(bus, _run)
    return StreamingResponse(bus.events(), media_type="text/event-stream")


def _probe_harmony_dir(pdir: Path) -> Path | None:
    """在工程附近找真正可编译的鸿蒙工程（与 GUI seal_step 同逻辑）；找不到返回 None。

    注意：不能返回 Path("")——str(Path("")) == "." 是真值，调用方
    bool(str(d)) 会谎报 ok（2026-10-25 实测踩坑）。
    """
    candidates: list[Path] = []
    harmony = pdir / "harmony"
    if harmony.is_dir():
        candidates.extend(sorted(p for p in harmony.iterdir() if p.is_dir()))
        candidates.append(harmony)
    for up in (pdir.parent, pdir.parent.parent):
        h = up / "harmony"
        if h.is_dir():
            candidates.extend(sorted(p for p in h.iterdir() if p.is_dir()))
    for c in candidates:
        if (c / "build-profile.json5").is_file():
            return c
    return None


@router.put("/projects/{pid}/seams/{sid}")
def api_update_seam(pid: str, sid: str, body: dict = Body(default={})) -> dict:
    cfg = app_config.load()
    pdir = core.resolve_project(pid, cfg)
    spec = core.load_spec(pdir)
    for s in spec.get("seams", []):
        if str(s.get("id")) == sid:
            if "status" in body:
                s["status"] = body["status"]
            if "verify_result" in body:
                s["verify_result"] = body["verify_result"]
            core.save_spec(pdir, spec)
            return {"ok": True, "item": s}
    raise HTTPException(404, f"缝不存在：{sid}")


@router.get("/projects/{pid}/harmony-dir")
def api_harmony_dir(pid: str) -> dict:
    cfg = app_config.load()
    pdir = core.resolve_project(pid, cfg)
    d = _probe_harmony_dir(pdir)
    return {"path": str(d) if d else "", "ok": d is not None}
