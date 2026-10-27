"""wbox.webapi.core —— Web API 的公共助手：工程定位 / spec 读写 / 目录守卫。

硬规则（与 GUI 侧一致，写死）：
1. spec 只经 wbox.spec 的 load/save 走，本模块不自己拼 JSON。
2. pid（工程标识）只允许单段 ASCII 目录名，拒绝路径穿越（../、绝对路径）。
3. 文件读取接口只放行工程目录内的相对路径，4MB 文本上限。
4. 工程目录名 ASCII 化（DevEco 不认中文目录，2026-10-25 铁律）——新建时
   由调用方用 wbox.ascii_names.work_dir_name 处理，这里只做校验。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from wbox import config as app_config
from wbox.spec import SPEC_VERSION, SpecError, load, save

_PID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_MAX_TEXT_BYTES = 4 * 1024 * 1024


def validate_pid(pid: str) -> str:
    if not _PID_RE.match(pid or ""):
        raise HTTPException(400, f"非法工程标识：{pid!r}（只允许单段 ASCII 目录名）")
    return pid


def _recent_paths(cfg: dict) -> dict[str, Path]:
    """最近工程表：name/目录名 → path（双别名）。

    为什么双别名：config 的 recent_projects 里 name 存的是 spec 的
    project.name（如 "Circular Saw"），而前端/CLI 习惯用目录名
    （如 "92934yjmnq8.wbox"）当 pid。两个键都指同一路径。
    """
    out: dict[str, Path] = {}
    for e in cfg.get("recent_projects", []):
        path = str(e.get("path", ""))
        if not path:
            continue
        name = str(e.get("name") or "")
        if name:
            out[name] = Path(path)
        out.setdefault(Path(path).name, Path(path))
    return out


def resolve_project(pid: str, cfg: dict | None = None) -> Path:
    """pid → 工程目录。查找序：最近工程表（双别名）→ 工作区 projects/ →
    base64 绝对路径回退（覆盖含中文等非法目录名的历史工程）。

    base64 回退存在的原因：最近列表里可能有仓库根目录那种中文名工程
    （桌面版历史遗留），目录名过不了 _PID_RE；前端对这类条目改用
    path_b64 字段（绝对路径的 base64url）作 pid。
    """
    cfg = cfg if cfg is not None else app_config.load()
    if _PID_RE.match(pid or ""):
        recent = _recent_paths(cfg)
        if pid in recent and (recent[pid] / "spec.json").is_file():
            return recent[pid]
        ws = app_config.workspace_root(cfg) / "projects" / pid
        if (ws / "spec.json").is_file():
            return ws
    # base64url 绝对路径回退
    try:
        import base64
        raw = base64.urlsafe_b64decode(pid + "=" * (-len(pid) % 4)).decode("utf-8")
        p = Path(raw)
        if p.is_absolute() and (p / "spec.json").is_file():
            return p.resolve()
    except Exception:  # noqa: BLE001  解码失败即不是合法回退 pid，落 404
        pass
    raise HTTPException(404, f"工程不存在：{pid}（最近工程、工作区与路径回退都没找到）")


def load_spec(project_dir: Path) -> dict:
    try:
        return load(project_dir / "spec.json")
    except (SpecError, OSError) as e:
        raise HTTPException(400, f"spec 加载失败：{e}") from e


def save_spec(project_dir: Path, spec: dict) -> None:
    try:
        save(spec, project_dir / "spec.json")
    except (SpecError, OSError) as e:
        raise HTTPException(500, f"spec 保存失败：{e}") from e


def safe_child(project_dir: Path, rel: str) -> Path:
    """把用户传来的相对路径解析成工程内的真实路径；越界即 400。"""
    rel = (rel or "").replace("\\", "/").strip("/")
    if not rel:
        return project_dir
    if rel.startswith("/") or re.match(r"^[A-Za-z]:", rel) or ".." in rel.split("/"):
        raise HTTPException(400, f"非法路径：{rel!r}")
    target = (project_dir / rel).resolve()
    root = project_dir.resolve()
    if target != root and root not in target.parents:
        raise HTTPException(400, f"路径越出工程目录：{rel!r}")
    return target


def list_dir(project_dir: Path, rel: str) -> list[dict]:
    """目录Listing：[{name, path, type: dir|file, size}]，目录在前、名称排序。"""
    base = safe_child(project_dir, rel)
    if not base.is_dir():
        raise HTTPException(404, f"目录不存在：{rel or '.'}")
    dirs, files = [], []
    try:
        for p in base.iterdir():
            try:
                st = p.stat()
            except OSError:
                continue
            item = {
                "name": p.name,
                "path": (p.relative_to(project_dir)).as_posix(),
                "type": "dir" if p.is_dir() else "file",
                "size": st.st_size,
                "mtime": st.st_mtime,
            }
            (dirs if p.is_dir() else files).append(item)
    except OSError as e:
        raise HTTPException(500, f"目录读取失败：{e}") from e
    dirs.sort(key=lambda x: x["name"].lower())
    files.sort(key=lambda x: x["name"].lower())
    return dirs + files


def read_text(project_dir: Path, rel: str) -> dict:
    """读工程内文本文件（4MB 上限）；二进制返回 is_text=false + 大小。"""
    target = safe_child(project_dir, rel)
    if not target.is_file():
        raise HTTPException(404, f"文件不存在：{rel}")
    size = target.stat().st_size
    if size > _MAX_TEXT_BYTES:
        return {"path": rel, "is_text": True, "too_large": True, "size": size,
                "content": f"（文件 {size:,} 字节，超过 4MB 内置预览上限，请下载后用专业工具查看）"}
    data = target.read_bytes()
    if b"\x00" in data[:8192]:
        return {"path": rel, "is_text": False, "size": size, "content": ""}
    return {"path": rel, "is_text": True, "too_large": False, "size": size,
            "content": data.decode("utf-8", errors="replace")}


def project_summary(project_dir: Path, spec: dict) -> dict:
    """工程卡片信息（首页/工作区头部用）。

    path_b64：绝对路径的 base64url——目录名非 ASCII（过不了 pid 校验）时，
    前端拿它当 pid 用（resolve_project 的 base64 回退通道）。
    """
    import base64
    proj = spec.get("project", {})
    return {
        "id": project_dir.name,
        "name": str(proj.get("name") or project_dir.name),
        "path": str(project_dir),
        "path_b64": base64.urlsafe_b64encode(
            str(project_dir).encode("utf-8")).decode("ascii").rstrip("="),
        "source": str(proj.get("source", "")),
        "created_at": str(proj.get("created_at", "")),
        "updated_at": str(proj.get("updated_at", "")),
        "counts": {
            "resources": len(spec.get("resources", [])),
            "modules": len(spec.get("modules", [])),
            "behaviors": len(spec.get("behaviors", [])),
            "decisions": len(spec.get("decisions", [])),
            "seams": len(spec.get("seams", [])),
            "build_log": len(spec.get("build_log", [])),
        },
    }


def create_project(project_dir: Path, apk_path: Path, name: str = "") -> dict:
    """新建工程：落一份最小合法 spec（空清单），等「拆」步填充。

    与 GUI 的 ProjectSession.create_new 同构（不引 PySide6——Web 服务端
    无 Qt 事件循环）；写盘一律经 wbox.spec.save 契约层。
    """
    project_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("work", "draft", "exports"):
        (project_dir / sub).mkdir(exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    spec = {
        "spec_version": SPEC_VERSION,
        "project": {
            "name": name or apk_path.stem,
            "source": str(apk_path),
            "target": "harmonyos-next",
            "created_at": now,
            "updated_at": now,
        },
        "resources": [], "modules": [], "behaviors": [],
        "decisions": [], "build_log": [], "seams": [],
    }
    save(spec, project_dir / "spec.json")
    return spec


class SpecSession:
    """wbox.hvigor.append_build_log 等复用件需要的最小 session 面（无 Qt）。

    GUI 的 ProjectSession 是 QObject；服务端只借它三个能力：spec 字典、
    next_id 自增、save 落盘。duck-typing 复用，避免为 Web 引整个 Qt。
    """

    def __init__(self, project_dir: Path, spec: dict) -> None:
        self.project_dir = Path(project_dir)
        self.spec = spec

    def next_id(self, section: str, prefix: str, width: int = 3) -> str:
        items = self.spec.get(section, [])
        max_n = 0
        for it in items:
            iid = str(it.get("id", ""))
            if iid.startswith(prefix):
                try:
                    max_n = max(max_n, int(iid[len(prefix):]))
                except ValueError:
                    pass
        return f"{prefix}{max_n + 1:0{width}d}"

    def save(self, note: str = "") -> None:
        save(self.spec, self.project_dir / "spec.json")
