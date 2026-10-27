"""wbox.shape —— 形态模板库：加载 / 打分 / 诊断。

存在理由：迁移的成败在动手前就基本定了——"这是个 Cordova 壳 + H5 游戏"和
"这是个 Unity il2cpp 原生包"是两条完全不同的路。形态模板把每类 APK 的
**识别规则**（detect）+ **迁移打法**（migrate：步骤/资源策略/桥接/坑/验收）
沉淀成 JSON，诊断仪据此在用户丢进 APK 的 30 秒内给出结论。

数据来源：src/wbox/shapes/*.json（一个文件一个形态）。模板是人工沉淀的经验，
本模块只负责加载与打分，不臆造结论——没命中就是没命中。

诊断输入支持两种：
  - 已解包目录（apktool 输出）
  - APK 文件本身（直接按 zip 读，不需要先解包，省一轮 apktool）
"""

from __future__ import annotations

import fnmatch
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

SHAPES_DIRNAME = "shapes"
META_FILENAME = "_meta.json"

# 扫描上限：contains 规则要读文件内容，超大包必须设闸，否则卡死 UI
_MAX_CONTENT_FILES = 40        # 每条 contains 规则最多读多少个文件
_MAX_FILE_BYTES = 512 * 1024   # 单文件最多读多少字节
_MAX_ENTRIES = 200000          # 条目（zip/目录）上限

_CACHE: list[dict] | None = None
_META_CACHE: dict | None = None


# ---------------------------------------------------------------- 数据结构


@dataclass
class Match:
    """一次形态命中：模板 + 得分 + 证据（证据必须能让人复核，不许只给结论）。"""

    shape: dict
    score: int = 0
    evidence: list[str] = field(default_factory=list)

    @property
    def shape_id(self) -> str:
        return str(self.shape.get("shape_id", ""))

    @property
    def name(self) -> str:
        return str(self.shape.get("name", self.shape_id))

    @property
    def confidence(self) -> str:
        if self.score >= 6:
            return "高"
        if self.score >= 3:
            return "中"
        return "低"


@dataclass
class ScanTarget:
    """被诊断对象的统一抽象：目录或 APK(zip)。"""

    path: Path
    is_zip: bool = False
    entries: list[str] = field(default_factory=list)

    def read_bytes(self, rel: str, limit: int = _MAX_FILE_BYTES) -> bytes:
        """读一个条目的前 limit 字节；读不到返回空 bytes（不抛）。"""
        try:
            if self.is_zip:
                with zipfile.ZipFile(self.path) as zf:
                    with zf.open(rel) as fh:
                        return fh.read(limit)
            target = self.path / rel
            if not target.is_file():
                return b""
            with open(target, "rb") as fh:
                return fh.read(limit)
        except (OSError, KeyError, zipfile.BadZipFile, ValueError):
            return b""


# ---------------------------------------------------------------- 加载


def shapes_dir() -> Path:
    """形态模板目录：src/wbox/shapes（与 templates/harmony 同一套定位方式）。

    用 __file__ 定位而不是 bundled_resource("shapes")：冻结态下 __file__ 在
    _MEIxxxx/wbox/ 里，与 wbox.spec 的 datas 目标目录 "wbox/shapes" 对齐；
    开发态就是仓库里的 src/wbox/shapes。两种形态同一条路径规则，不会漂。
    """
    return Path(__file__).resolve().parent / SHAPES_DIRNAME


def load_shapes(force: bool = False) -> list[dict]:
    """加载全部形态模板；目录不存在或全坏时返回空列表（不抛，UI 要能起来）。"""
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE
    d = shapes_dir()
    items: list[dict] = []
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(data, dict) and data.get("shape_id"):
                data["_file"] = p.name
                items.append(data)
    _CACHE = items
    return items


def load_meta(force: bool = False) -> dict | None:
    """加载 `_meta.json`（"三条铁律"），文件不存在返回 None。

    为什么单独一个函数：load_shapes() 按约定跳过下划线开头的文件（它们不是形态），
    但 _meta.json 里的版本说明与三条铁律必须在知识库首页显眼地展示——
    那是用户明确要的"先讲结论"，不能塞在某个二级页里。
    """
    global _META_CACHE
    if _META_CACHE is not None and not force:
        return _META_CACHE
    path = shapes_dir() / META_FILENAME
    data: dict | None = None
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            raw = None
        if isinstance(raw, dict):
            data = raw
    _META_CACHE = data
    return data


def meta_rules() -> list[dict]:
    """取铁律列表（容错：字段缺失返回空，UI 据此决定要不要画这一块）。"""
    meta = load_meta() or {}
    rules = meta.get("rules")
    return [r for r in rules if isinstance(r, dict)] if isinstance(rules, list) else []


def get_shape(shape_id: str) -> dict | None:
    return next((s for s in load_shapes() if s.get("shape_id") == shape_id), None)


def shape_tags() -> list[str]:
    tags: list[str] = []
    for s in load_shapes():
        for t in s.get("tags", []) or []:
            if t not in tags:
                tags.append(t)
    return tags


# ---------------------------------------------------------------- glob


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """把模板里的 path_glob 编译成正则（支持 ** 跨目录）。"""
    out: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "*":
            if pattern.startswith("**", i):
                out.append(".*")
                i += 2
                if i < n and pattern[i] == "/":
                    i += 1       # **/ 允许匹配零层
                continue
            out.append("[^/]*")
            i += 1
            continue
        if ch == "?":
            out.append("[^/]")
            i += 1
            continue
        out.append(re.escape(ch))
        i += 1
    return re.compile("^" + "".join(out) + "$", re.IGNORECASE)


def match_glob(rel: str, pattern: str) -> bool:
    """条目相对路径是否命中 glob（先走便宜的 fnmatch，再走 ** 正则）。"""
    rel = rel.replace("\\", "/")
    if fnmatch.fnmatch(rel.lower(), pattern.lower()):
        return True
    if "**" in pattern:
        return bool(_glob_to_regex(pattern).match(rel))
    return False


# ---------------------------------------------------------------- 扫描对象


def open_target(target: str | Path) -> ScanTarget:
    """把 APK 或解包目录抽象成 ScanTarget（只列条目，不读内容）。"""
    p = Path(target)
    if p.is_file():
        entries: list[str] = []
        try:
            with zipfile.ZipFile(p) as zf:
                for info in zf.infolist():
                    if not info.is_dir():
                        entries.append(info.filename.replace("\\", "/"))
                    if len(entries) >= _MAX_ENTRIES:
                        break
        except (zipfile.BadZipFile, OSError):
            entries = []
        return ScanTarget(path=p, is_zip=True, entries=entries)
    entries = []
    if p.is_dir():
        try:
            for f in p.rglob("*"):
                if f.is_file():
                    entries.append(f.relative_to(p).as_posix())
                if len(entries) >= _MAX_ENTRIES:
                    break
        except OSError:
            pass
    return ScanTarget(path=p, is_zip=False, entries=entries)


# ---------------------------------------------------------------- 打分


def _rule_glob(rule: dict) -> str:
    """取规则里的 glob：模板里两种写法都合法（path_glob / smali_glob）。"""
    return str(rule.get("path_glob") or rule.get("smali_glob") or "")


def _score_shape(shape: dict, target: ScanTarget) -> Match | None:
    detect = shape.get("detect") or {}
    match = Match(shape=shape)
    entries = target.entries

    def add_evidence(text: str) -> None:
        if text not in match.evidence:      # 去重：同一文件常被多条规则命中
            match.evidence.append(text)

    # 1) 存在性证据（any）：命中加分；absent=true 时"不存在"才是特征
    for rule in detect.get("any", []) or []:
        pat = _rule_glob(rule)
        if not pat:
            continue
        hit = next((e for e in entries if match_glob(e, pat)), None)
        if bool(rule.get("absent")):
            if hit is None:
                match.score += 2
                add_evidence(f"未发现 {pat}（该形态的典型特征就是没有它）")
            continue
        if hit is not None:
            match.score += 2
            add_evidence(f"存在 {hit}")

    # 2) 内容证据（contains）：有 pattern 就读文件找特征串；没 pattern 只认"该文件存在"
    for rule in detect.get("contains", []) or []:
        pat = _rule_glob(rule)
        if not pat:
            continue
        pattern = str(rule.get("pattern", "") or "")
        if not pattern:
            hit = next((e for e in entries if match_glob(e, pat)), None)
            if hit is not None:
                match.score += 2
                add_evidence(f"存在 {hit}")
            continue
        try:
            rx = re.compile(pattern)
        except re.error:
            continue
        checked = 0
        for rel in entries:
            if checked >= _MAX_CONTENT_FILES:
                break
            if not match_glob(rel, pat):
                continue
            checked += 1
            blob = target.read_bytes(rel)
            if not blob:
                continue
            text = blob.decode("utf-8", errors="ignore")
            if rx.search(text):
                match.score += 3
                add_evidence(f"{rel} 含特征串 /{pattern}/")
                break

    # 3) 反向证据（exclude）：命中即扣分，用于排除"像但不是"
    for rule in detect.get("exclude", []) or []:
        pat = _rule_glob(rule)
        if not pat:
            continue
        hit = next((e for e in entries if match_glob(e, pat)), None)
        if hit is not None:
            match.score -= 4
            add_evidence(f"排除项命中 {hit}（更像别的形态）")

    if match.score <= 0:
        return None
    return match


def detect_shape(target: str | Path) -> list[Match]:
    """诊断一个 APK / 解包目录，返回命中的形态（按得分降序；无命中返回空列表）。"""
    scan = open_target(target)
    if not scan.entries:
        return []
    matches: list[Match] = []
    for shape in load_shapes():
        m = _score_shape(shape, scan)
        if m is not None:
            matches.append(m)
    matches.sort(key=lambda m: m.score, reverse=True)
    return matches


# ---------------------------------------------------------------- 报告（纯文本，CLI/日志共用）


def report_text(target: str | Path, matches: list[Match]) -> str:
    """把诊断结果写成人话报告（诊断仪与 CLI 共用同一份措辞）。"""
    lines = [f"诊断对象：{target}"]
    if not matches:
        lines.append("")
        lines.append("未命中任何已知形态模板。")
        lines.append("可能原因：模板库尚未覆盖该类型，或 APK 未解包/不可读。")
        lines.append("建议：先用「① 拆」解包，再按资源构成人工判读；"
                     "也欢迎把这类样本补充进 src/wbox/shapes/。")
        return "\n".join(lines)
    top = matches[0]
    lines.append("")
    lines.append(f"最可能形态：{top.name}（形态 ID：{top.shape_id}，置信度：{top.confidence}）")
    summary = str(top.shape.get("summary", "")).strip()
    if summary:
        lines.append(f"一句话：{summary}")
    effort = str(top.shape.get("effort", "")).strip()
    if effort:
        lines.append(f"预计工作量：{effort}")
    lines.append("")
    lines.append("判定证据：")
    for e in top.evidence:
        lines.append(f"  · {e}")
    migrate = top.shape.get("migrate") or {}
    steps = migrate.get("steps") or []
    if steps:
        lines.append("")
        lines.append("迁移步骤：")
        for i, s in enumerate(steps, 1):
            lines.append(f"  {i}. {s}")
    pitfalls = migrate.get("pitfalls") or []
    if pitfalls:
        lines.append("")
        lines.append("已知坑（按出现频率排序）：")
        for p in pitfalls:
            lines.append(f"  · 现象：{p.get('symptom', '')}")
            lines.append(f"    原因：{p.get('cause', '')}")
            lines.append(f"    解法：{p.get('fix', '')}")
    verify = migrate.get("verify") or []
    if verify:
        lines.append("")
        lines.append("验收清单：")
        for v in verify:
            lines.append(f"  □ {v}")
    if len(matches) > 1:
        lines.append("")
        lines.append("其他可能形态：" + "、".join(
            f"{m.name}（{m.confidence}）" for m in matches[1:]))
    return "\n".join(lines)


def iter_shapes() -> Iterable[dict]:
    return iter(load_shapes())


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="WBox 形态诊断")
    parser.add_argument("target", help="APK 文件或已解包目录")
    parser.add_argument("--list", action="store_true", help="只列出全部形态模板")
    args = parser.parse_args(argv)

    if args.list:
        for s in load_shapes():
            print(f"{s.get('shape_id'):<28}{s.get('name', '')}")
            print(f"{'':<28}工作量：{s.get('effort', '—')}  标签：{'、'.join(s.get('tags', []) or [])}")
        return 0
    print(report_text(args.target, detect_shape(args.target)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
