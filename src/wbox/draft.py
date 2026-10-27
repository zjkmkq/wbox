"""wbox.draft —— 把 AI 输出的 FILE 格式文本落盘成鸿蒙草案工程树。

输入约定（taskpack.METHODOLOGY 第 4 节，写死）：
    ```ets
    // FILE: pages/GamePage.ets
    <文件完整内容>
    ```
一个文件一段，FILE 行必须与提案 target 完全一致。

安全规则（写死）：
- 只接受相对路径；拒绝对盘符/UNC/.. 越界/空路径。
- 目标根目录由调用方给定（GUI 侧为 <project>/draft）。
- 不覆盖 spec.json（契约不走本通道）。
- 陈旧草案清理：只删「上一次 apply_draft 自己写入、本次没再输出」的文件
  （凭 draft/.wbox-manifest.json 清单）。人工手动放进 draft/ 的文件不在清单里，
  永不误删。防的是提案变更后旧文件阴魂不散（Web 壳工程 134 个框架类实测）。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# 围栏代码块：```lang\n...\n```
_FENCE_RE = re.compile(r"```[ \t]*[A-Za-z0-9_+-]*[ \t]*\r?\n(.*?)```", re.S)
_FILE_RE = re.compile(r"^[ \t]*//[ \t]*FILE:[ \t]*(.+?)[ \t]*$")
# 输出末尾的附加节（提示人工的缝 / 映射核对表），不属于文件内容
_NOTES_MARKERS = ("建议补充的缝", "映射核对表", "## 建议补充", "## 映射核对")
# 上一次落盘清单：只凭它识别"自己写的"文件，人工文件永不进清单
_MANIFEST = ".wbox-manifest.json"


@dataclass
class DraftResult:
    written: list[str] = field(default_factory=list)   # 相对路径
    skipped: list[str] = field(default_factory=list)   # 被拒路径 + 原因
    notes: str = ""                                     # 附加节原文（缝清单/核对表）
    content: dict[str, str] = field(default_factory=dict)  # rel -> 文件内容
    pruned: list[str] = field(default_factory=list)     # 上次写入、本次未再输出而被删的文件


def _safe_rel(raw: str) -> Path | None:
    """归一化并校验相对路径；不合法返回 None。"""
    p = raw.strip().replace("\\", "/").lstrip("/")
    if not p or ":" in p or p.startswith("//"):
        return None
    parts = []
    for seg in p.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            return None
        parts.append(seg)
    if not parts:
        return None
    return Path(*parts)


def parse_draft(text: str) -> DraftResult:
    """从 AI 输出文本解析 FILE 段（不落盘，供预览/测试）。"""
    result = DraftResult()
    seen: set[str] = set()
    for m in _FENCE_RE.finditer(text):
        block = m.group(1)
        lines = block.splitlines()
        # 找块内首个 FILE: 行
        idx = next((i for i, ln in enumerate(lines) if _FILE_RE.match(ln)), -1)
        if idx < 0:
            continue
        rel = _FILE_RE.match(lines[idx])
        assert rel is not None
        target = _safe_rel(rel.group(1))
        if target is None:
            result.skipped.append(f"非法路径：{rel.group(1)}")
            continue
        content = "\n".join(lines[idx + 1:]).strip("\n")
        if not content.strip():
            result.skipped.append(f"空内容：{target.as_posix()}")
            continue
        key = target.as_posix()
        if key in seen:
            result.skipped.append(f"重复输出（后者忽略）：{key}")
            continue
        seen.add(key)
        result.written.append(key)
        result.content[key] = content
    # 附加节：截取建议补充的缝 / 映射核对表 文本
    for marker in _NOTES_MARKERS:
        pos = text.find(marker)
        if pos >= 0:
            result.notes = text[pos:].strip()
            break
    return result


def _inside(root: Path, target: Path) -> bool:
    """target 必须落在 root 内（防清单被动手脚后越界删除）。"""
    try:
        target.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _read_manifest(root: Path) -> list[str]:
    p = root / _MANIFEST
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return [str(x) for x in (data.get("written") or [])]
    except (OSError, ValueError):
        return []


def _write_manifest(root: Path, written: list[str]) -> None:
    p = root / _MANIFEST
    tmp = root / f".{_MANIFEST}.tmp"
    tmp.write_text(json.dumps({"written": sorted(written)}, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8", newline="\n")
    os.replace(tmp, p)


def apply_draft(text: str, draft_dir: str | Path) -> DraftResult:
    """解析并落盘。返回写入清单/跳过清单/附加节。"""
    parsed = parse_draft(text)
    root = Path(draft_dir)
    root.mkdir(parents=True, exist_ok=True)
    for rel in parsed.written:
        content = parsed.content[rel]
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        # newline="\n"：Windows 下 write_text 默认把 \n 翻译成 \r\n，
        # 与全链路 LF 契约（spec/git）冲突，必须显式锁定
        dest.write_text(content + "\n", encoding="utf-8", newline="\n")
    # 陈旧草案清理：只删「上一次 apply_draft 自己写的、且本次没再输出」的文件。
    # 人工手动放进 draft/ 的文件不在清单里，永不误删——所以哪怕 AI 这次只吐了
    # 1 个文件，也不会把另外 2 个人工文件删掉。
    for rel in _read_manifest(root):
        if rel in parsed.written or rel == _MANIFEST:
            continue
        victim = root / rel
        if not _inside(root, victim) or not victim.is_file():
            continue
        try:
            victim.unlink()
            parsed.pruned.append(rel)
        except OSError:
            pass
    _write_manifest(root, parsed.written)
    return parsed


def draft_summary(result: DraftResult) -> str:
    parts = [f"写入 {len(result.written)} 个文件"]
    if result.pruned:
        parts.append(f"清理陈旧草案 {len(result.pruned)} 个（上次生成、本次未再输出）")
    if result.skipped:
        parts.append(f"跳过 {len(result.skipped)} 段（{'；'.join(result.skipped[:5])}）")
    if result.notes:
        head = result.notes.splitlines()[0][:60]
        parts.append(f"另有附加节：{head}…")
    return "；".join(parts)


if __name__ == "__main__":  # CLI 自测：python -m wbox.draft <文本文件> <目标目录>
    import sys

    if len(sys.argv) >= 3:
        r = apply_draft(Path(sys.argv[1]).read_text(encoding="utf-8"), sys.argv[2])
        print(draft_summary(r))
        for f in r.written:
            print("  +", f)
        for s in r.skipped:
            print("  -", s)
    else:
        print("usage: python -m wbox.draft <ai-output.md> <draft-dir>")
