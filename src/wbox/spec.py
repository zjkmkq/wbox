"""wbox.spec —— spec.json 契约层：全工作台的唯一纽带。

硬规则（写死，不许绕）：
1. spec_version 必须等于 SPEC_VERSION；版本不符走注册的迁移链逐版升级，
   禁止手工改文件、禁止加载方直接吞旧版本。
2. 保存为原子写：先写同目录临时文件再 os.replace，崩溃不留半个 spec。
3. 每次保存自动刷新 project.updated_at（UTC）。
4. 所有模块（CLI 或主控）只准通过本模块读写 spec，不允许各自 json.load。
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from jsonschema import Draft202012Validator

from wbox.paths import bundled_resource

SPEC_VERSION = "1.0.0"

# schema 位置：开发态为仓库根，冻结态为 PyInstaller 解包目录（datas 规则打包）。
# 不能用 __file__.parents[N]——onefile 下 __file__ 在 _MEIxxxxx 里，
# parents[2] 会错指到 _MEIxxxxx 的父目录（Temp），正是"找不到 schema"的根因
_SCHEMA_PATH = bundled_resource("spec.schema.json")

# 迁移注册表：from_version -> 升级函数（入参旧 spec，返回新 spec）。
_MIGRATIONS: dict[str, Callable[[dict], dict]] = {}


class SpecError(Exception):
    """spec 契约错误：版本不符、校验失败、迁移链断裂等。"""


def register_migration(from_version: str) -> Callable:
    """注册一个迁移：把 from_version 的 spec 升级到下一个版本。

    用法::

        @register_migration("0.9.0")
        def _to_1_0_0(spec: dict) -> dict:
            spec["seams"] = spec.pop("issues", [])
            spec["spec_version"] = "1.0.0"
            return spec
    """

    def decorator(fn: Callable[[dict], dict]) -> Callable[[dict], dict]:
        _MIGRATIONS[from_version] = fn
        return fn

    return decorator


def _vtuple(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError as exc:
        raise SpecError(f"非法版本号：{version!r}（应为 x.y.z）") from exc


def migrate(spec: dict) -> dict:
    """按迁移链把旧版本 spec 升到当前版本；链断裂直接报错。"""
    version = spec.get("spec_version")
    if not version:
        raise SpecError("spec 缺少 spec_version 字段")
    if version == SPEC_VERSION:
        return spec

    pending = [
        src
        for src in _MIGRATIONS
        if _vtuple(src) >= _vtuple(version) and _vtuple(src) < _vtuple(SPEC_VERSION)
    ]
    if not pending:
        raise SpecError(
            f"没有从 {version} 到 {SPEC_VERSION} 的迁移脚本；"
            "请先补 register_migration，再加载旧 spec"
        )

    spec = copy.deepcopy(spec)
    for src in sorted(pending, key=_vtuple):
        spec = _MIGRATIONS[src](spec)
    if spec.get("spec_version") != SPEC_VERSION:
        raise SpecError(
            f"迁移链断裂：{version} 经 {pending} 后停在 {spec.get('spec_version')}"
        )
    return spec


def validate(spec: dict) -> None:
    """按 spec.schema.json 校验 spec；失败抛 SpecError，指出第一个出错位置。"""
    if not _SCHEMA_PATH.exists():
        raise SpecError(f"找不到 schema 文件：{_SCHEMA_PATH}")
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(
        schema, format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    errors = sorted(validator.iter_errors(spec), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        where = "/".join(str(part) for part in first.absolute_path) or "<root>"
        raise SpecError(f"spec 校验失败：{where} — {first.message}")


def load(path: str | Path) -> dict:
    """加载 spec：读文件 → 迁移版本 → 校验。任何一步失败抛 SpecError。"""
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    spec = migrate(spec)
    validate(spec)
    return spec


def save(spec: dict, path: str | Path) -> None:
    """保存 spec：版本检查 → 刷新 updated_at → 校验 → 原子写。"""
    if spec.get("spec_version") != SPEC_VERSION:
        raise SpecError(
            f"拒绝保存 spec_version={spec.get('spec_version')!r}（当前 {SPEC_VERSION}）"
        )
    spec = copy.deepcopy(spec)
    spec.setdefault("project", {})["updated_at"] = datetime.now(
        timezone.utc
    ).isoformat()
    validate(spec)

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    try:
        # newline="\n"：锁定 LF（Windows 文本模式默认会把 \n 写成 \r\n）
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(spec, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp_name, target)
    except BaseException:
        # 清理失败的临时文件不能盖住真正的异常：os.replace 撞上 WinError 32
        # （另一个进程占着 spec.json，典型是桌面 GUI 在跑）时，unlink 同样会
        # PermissionError——原来这么写会把「保存失败」伪装成「清理失败」。
        try:
            Path(tmp_name).unlink(missing_ok=True)
        except OSError:
            pass
        raise
