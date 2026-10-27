"""wbox.extract —— 阶段 1「拆」：APK → 资源清单 / 模块骨架 / 行为骨架。

职责边界（写死，不许越界）：
- 只产出机器可推导的草稿：manifest 里的 Activity / Application、res/ 与 assets/ 的
  文件清单、smali 代码统计。逻辑说明和行为细节留给阶段 2 的人工 + AI，不在这里猜。
- 所有 spec 写入必须经 wbox.spec.save，不允许自己拼 JSON 落盘。
- 重复提取不毁人工记录：--force 时保留 decisions / seams，build_log 追加不清空。

CLI 用法：
    python -m wbox.extract <apk> [--spec spec.json] [--workdir work/RE]
                            [--apktool-jar 路径] [--java java]
                            [--no-decode] [--force]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from wbox.ascii_names import work_dir_name
from wbox.paths import bundled_root
from wbox.spec import SPEC_VERSION, SpecError, load, save

# 开发态=仓库根，冻结态=PyInstaller 解包目录。注意：ROOT 在冻结态是**只读**的，
# 仅可用于找配置/资源；默认 workdir 不许落这里（用 cwd），否则 exe 新建工程时
# 解包产物会落临时目录、重启即丢
ROOT = bundled_root()

ANDROID_NS = "{http://schemas.android.com/apk/res/android}"

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
AUDIO_EXT = {".mp3", ".ogg", ".wav", ".m4a", ".flac"}
FONT_EXT = {".ttf", ".otf", ".ttc"}


class ExtractError(Exception):
    """提取失败：apktool 报错、spec 已存在、缺少工具配置等。"""


# ---------------------------------------------------------------- 工具调用


def _load_tool_config(jar_override: str | None, java_override: str | None) -> tuple[str, str]:
    """从 wbox.config.json 读 apktool 的 java / jar 路径，命令行参数优先。"""
    java = java_override or "java"
    jar = jar_override
    cfg_path = ROOT / "wbox.config.json"
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        tool = cfg.get("tools", {}).get("apktool", {})
        jar = jar or tool.get("jar")
        java = java_override or tool.get("java", "java")
    if not jar:
        raise ExtractError(
            "未配置 apktool：请在 wbox.config.json 的 tools.apktool.jar 填 jar 路径，"
            "或用 --apktool-jar 指定"
        )
    return java, jar


def run_apktool(apk: Path, out_dir: Path, java: str, jar: str) -> None:
    """调 apktool 解包；失败时带 stderr 尾巴抛 ExtractError。"""
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    cmd = [java, "-jar", jar, "d", str(apk), "-o", str(out_dir), "-f"]
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-2000:]
        raise ExtractError(f"apktool 解包失败（退出码 {proc.returncode}）：\n{tail}")


# ---------------------------------------------------------------- manifest


def _parse_manifest(decoded: Path) -> dict:
    """解析 AndroidManifest.xml，取出包名、权限、Activity、Application。"""
    manifest_file = decoded / "AndroidManifest.xml"
    if not manifest_file.exists():
        raise ExtractError(f"解包目录里没有 AndroidManifest.xml：{decoded}")
    root = ET.parse(manifest_file).getroot()
    package = root.get("package", "")

    permissions = [
        p.get(ANDROID_NS + "name", "")
        for p in root.findall("uses-permission")
        if p.get(ANDROID_NS + "name")
    ]

    app_el = root.find("application")
    app_name = ""
    activities: list[dict] = []
    if app_el is not None:
        app_name = app_el.get(ANDROID_NS + "name", "")
        for act in app_el.findall("activity"):
            name = act.get(ANDROID_NS + "name", "")
            if not name:
                continue
            has_launcher = any(
                cat.get(ANDROID_NS + "name") == "android.intent.category.LAUNCHER"
                for filt in act.findall("intent-filter")
                for cat in filt.findall("category")
            )
            activities.append(
                {
                    "name": name,
                    "exported": act.get(ANDROID_NS + "exported", ""),
                    "orientation": act.get(ANDROID_NS + "screenOrientation", ""),
                    "config_changes": act.get(ANDROID_NS + "configChanges", ""),
                    "has_launcher": has_launcher,
                }
            )
    return {
        "package": package,
        "permissions": permissions,
        "application": app_name,
        "activities": activities,
    }


def _app_label(root: ET.Element, decoded: Path) -> str:
    """解析应用名：label 可能是 @string/xxx，需要去 strings.xml 里找真身。"""
    app_el = root.find("application")
    label = app_el.get(ANDROID_NS + "label") if app_el is not None else None
    if not label:
        return root.get("package", "unknown")
    if label.startswith("@string/"):
        key = label.split("/", 1)[1]
        strings_file = decoded / "res" / "values" / "strings.xml"
        if strings_file.exists():
            for s in ET.parse(strings_file).getroot().findall("string"):
                if s.get("name") == key:
                    return (s.text or key).strip()
        return key
    return label


def _short_name(full: str) -> str:
    return full.rsplit(".", 1)[-1] if full else "unknown"


# ---------------------------------------------------------------- 资源扫描


def _type_for(base: str, ext: str) -> str:
    if ext in IMAGE_EXT or base in {"mipmap", "drawable"}:
        return "image"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in FONT_EXT:
        return "font"
    if base in {"anim", "animator"}:
        return "animation"
    return "config"


def _default_disposition(rtype: str, fmt: str) -> str:
    """机器初判：图片格式鸿蒙直接支持算 reuse，音频多半要转，其余一律等人确认。"""
    if rtype == "image" and fmt in {"png", "webp", "jpg", "jpeg"}:
        return "reuse"
    if rtype == "audio":
        return "convert"
    return "confirm"


def _scan_values(values_dir: Path) -> list[tuple[tuple, dict]]:
    """扫 res/values/：strings 逐条列；public.xml 是 apktool 产物，跳过。"""
    out: list[tuple[tuple, dict]] = []
    for f in sorted(values_dir.glob("*.xml")):
        if f.name == "public.xml":
            continue
        if f.name.startswith("strings"):
            try:
                root = ET.parse(f).getroot()
            except ET.ParseError:
                root = None
            if root is not None:
                for s in root.findall("string"):
                    name = s.get("name", "")
                    text = (s.text or "").strip()
                    if not name:
                        continue
                    out.append(
                        (
                            ("text", name),
                            {
                                "name": name,
                                "type": "text",
                                "format": "xml",
                                "size_bytes": f.stat().st_size,
                                "usage": f"字符串「{text[:40]}」",
                                "disposition": "confirm",
                                "notes": f"res/values/{f.name}",
                            },
                        )
                    )
                continue
        out.append(
            (
                ("config", f.stem),
                {
                    "name": f.stem,
                    "type": "config",
                    "format": "xml",
                    "size_bytes": f.stat().st_size,
                    "usage": f"values 资源文件（{f.name}）",
                    "disposition": "confirm",
                    "notes": f"res/values/{f.name}",
                },
            )
        )
    return out


def _scan_resources(decoded: Path) -> list[dict]:
    """扫 res/ 与 assets/，返回按 (type, name) 排序、带稳定 id 的资源清单。"""
    collected: list[tuple[tuple, dict]] = []

    res_dir = decoded / "res"
    if res_dir.is_dir():
        image_groups: dict[tuple[str, str], dict] = {}
        for child in sorted(res_dir.iterdir()):
            if not child.is_dir():
                continue
            base, _, qualifier = child.name.partition("-")
            if base == "values":
                collected.extend(_scan_values(child))
                continue
            for f in sorted(child.iterdir()):
                if not f.is_file():
                    continue
                ext = f.suffix.lower()
                rtype = _type_for(base, ext)
                fmt = ext.lstrip(".") or "unknown"
                size = f.stat().st_size
                if rtype == "image":
                    key = (base, f.stem)
                    if key in image_groups:
                        image_groups[key]["notes"] += f", {qualifier or 'default'}"
                        continue
                    entry = {
                        "name": f.stem,
                        "type": "image",
                        "format": fmt,
                        "size_bytes": size,
                        "usage": f"{base} 资源（多密度变体）",
                        "disposition": _default_disposition(rtype, fmt),
                        "notes": f"密度变体: {qualifier or 'default'}",
                    }
                    image_groups[key] = entry
                    collected.append(((rtype, f.stem), entry))
                    continue
                collected.append(
                    (
                        (rtype, f.stem),
                        {
                            "name": f.stem,
                            "type": rtype,
                            "format": fmt,
                            "size_bytes": size,
                            "usage": f"{base} 资源",
                            "disposition": _default_disposition(rtype, fmt),
                            "notes": f"res/{child.name}/{f.name}",
                        },
                    )
                )

    assets_dir = decoded / "assets"
    if assets_dir.is_dir():
        for f in sorted(assets_dir.rglob("*")):
            if not f.is_file():
                continue
            ext = f.suffix.lower()
            rtype = _type_for("", ext)
            collected.append(
                (
                    (rtype, f.name),
                    {
                        "name": str(f.relative_to(assets_dir)),
                        "type": rtype,
                        "format": ext.lstrip(".") or "unknown",
                        "size_bytes": f.stat().st_size,
                        "usage": "assets 资源",
                        "disposition": _default_disposition(rtype, ext.lstrip(".")),
                        "notes": f"assets/{f.relative_to(assets_dir)}",
                    },
                )
            )

    unknown_dir = decoded / "unknown"
    if unknown_dir.is_dir():
        for item in sorted(unknown_dir.iterdir()):
            note = "apktool 未能识别的文件，需人工确认用途"
            if item.name == "META-INF":
                note = "原 APK 签名信息，上架前置条件参考"
            size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
            collected.append(
                (
                    ("config", item.name),
                    {
                        "name": item.name,
                        "type": "config",
                        "format": "unknown",
                        "size_bytes": size,
                        "usage": note,
                        "disposition": "confirm",
                        "notes": f"unknown/{item.name}",
                    },
                )
            )

    collected.sort(key=lambda pair: pair[0])
    resources = [entry for _, entry in collected]
    for i, entry in enumerate(resources, 1):
        entry_with_id = {"id": f"res_{i:03d}", **entry}
        resources[i - 1] = entry_with_id
    return resources


# ---------------------------------------------------------------- 代码统计


# 已知库包前缀（smali 目录下的相对路径前缀）。这些不算自有代码。
_LIB_PKG_PREFIXES = (
    "android/", "androidx/", "kotlin/", "kotlinx/", "com/google/",
    "com/android/", "com/badlogic/", "com/facebook/", "com/unity/",
    "com/unity3d/", "com/applovin/", "com/vungle/", "com/ironsource/",
    "com/mopub/", "com/inmobi/", "com/chartboost/", "com/tapjoy/",
    "com/crashlytics/", "com/squareup/", "okhttp3/", "retrofit2/",
    "io/reactivex/", "dagger/", "javax/", "org/apache/", "org/json/",
    "bolts/", "pl/droidsonroids/", "de/greenrobot/", "com/google/firebase/",
)
# 混淆产物的短包名（R8/ProGuard 把自有代码搬到顶级短包）：a, a0, b, w0...
_OBFUSCATED_PKG_RE = re.compile(r"^[a-z]{1,2}\d*$")


def _is_own_pkg(rel: str, own_prefix: str = "") -> bool:
    """smali 相对路径是否属于自有代码包。

    判定：已知库前缀 → False；manifest 包子树 → True（自有代码的定义）；
    顶级短名（混淆自有）→ True；com/<x>/ 非库 → True；其他顶级包
    （io/bolts 等）→ False。
    误判风险由 disposition=confirm 兜底（人工复核），但漏判游戏核心
    类（w0 包这类）是提案器的致命缺陷，故宁可错收不可漏。
    """
    top = rel.split("/", 1)[0]
    if top in ("android", "androidx", "kotlin", "kotlinx", "javax", "io",
               "okhttp3", "retrofit2", "dagger", "bolts"):
        return False
    if rel.startswith(_LIB_PKG_PREFIXES):
        return False
    if own_prefix and (rel == own_prefix or rel.startswith(own_prefix + "/")):
        return True
    if _OBFUSCATED_PKG_RE.match(top):
        return True
    if top == "com" or top.startswith("com/"):
        return True
    return False


def _code_stats(decoded: Path, reachable_own: set[str]) -> tuple[int, int]:
    """数 smali：自有代码（入口闭包内的自有类）与库代码分类计数。

    reachable_own 必须是入口闭包过滤后的自有类集合——混淆工程里
    顶级短包一大片（本样本 1218 个类），直接按包名算会把 androidx
    混淆类全算成自有，数字失去意义。
    """
    smali_dir = decoded / "smali"
    if not smali_dir.is_dir():
        return 0, 0
    total = sum(1 for _ in smali_dir.rglob("*.smali"))
    own = len(reachable_own)
    return own, max(total - own, 0)


def _smali_meta(path: Path) -> tuple[str, str]:
    """读 smali 头部，取 (外壳方法, 继承/实现线索)。

    只扫前 40 行：.super / .implements / EnclosingMethod 都在头部。
    匿名类（EnclosingMethod）的定位线索对判断职责极关键——libGDX 壳游戏
    的逻辑几乎全在 onCreate/h() 这类方法里 new 出来的匿名类中。
    注意 EnclosingMethod 注解跨两行，必须在原文上匹配（不能逐行 strip）。
    """
    enclosing = ""
    hint = ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return enclosing, hint
    m = re.search(r"EnclosingMethod;\s*value = \S+;->(\w+)\(", text)
    if m:
        enclosing = m.group(1)
    m = re.search(r"\.implements\s+L([^;]+);", text)
    if m:
        hint = m.group(1).replace("/", ".")
    else:
        m = re.search(r"\.super\s+L([^;]+);", text)
        if m:
            sup = m.group(1).replace("/", ".")
            if sup != "java.lang.Object":
                hint = sup
    return enclosing, hint


_TYPE_REF_RE = re.compile(r"L([A-Za-z_][A-Za-z0-9_/$]*);")


def _own_reachable(decoded: Path, entry_classes: list[str],
                   own_prefix: str = "") -> set[str]:
    """从入口类沿 smali 类型引用做 BFS，返回可达的自有候选类集合。

    为什么需要：R8 混淆把库代码也搬到顶级短包（a/a0/.../z3），单看包名
    无法区分"自有混淆"与"库混淆"。只有从 manifest 入口可达的才是自有
    （w0.g 被 AndroidLauncher new 出来 → 游戏核心；AndroidX 的 a/a0 只被
    框架引用，入口不直接碰 →  correctly excluded）。
    传播规则：只走进 _is_own_pkg 的候选（manifest 包子树/短包/com 非库）；
    引擎/框架/公共库命名空间（com/badlogic、android.* 等）是叶子，不继续传播。
    **入口必须是调用方筛过的自有组件**——库组件（AdActivity 等）会把
    androidx 混淆短包带进闭包，那是库噪音不是游戏核心。
    """
    smali_dir = decoded / "smali"
    if not smali_dir.is_dir():
        return set()
    refs: dict[str, set[str]] = {}
    for f in smali_dir.rglob("*.smali"):
        rel = f.relative_to(smali_dir).as_posix()[:-len(".smali")]
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        refs[rel] = set(_TYPE_REF_RE.findall(text))
    seen: set[str] = set()
    stack = [c.replace(".", "/") for c in entry_classes]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        for nxt in refs.get(cur, ()):
            if nxt in seen or not _is_own_pkg(nxt, own_prefix):
                continue
            stack.append(nxt)
    return seen


def _own_packages(decoded: Path, reachable: set[str] | None = None,
                  own_prefix: str = "") -> list[tuple[str, dict[str, list[dict]]]]:
    """扫 smali，按自有包聚合 {顶层类: [内部类 entry...]}。

    返回 [(包路径, {顶层类: [...]}), ...]，按包路径排序。
    reachable 非空时只收入口闭包内的类——过滤掉库代码的混淆短包
    （AndroidX 被 R8 搬到 a/a0/...，不可达则不是自有代码）。
    """
    smali_dir = decoded / "smali"
    if not smali_dir.is_dir():
        return []
    pkgs: dict[str, dict[str, list[dict]]] = {}
    for f in smali_dir.rglob("*.smali"):
        rel = f.relative_to(smali_dir).as_posix()
        if not _is_own_pkg(rel, own_prefix):
            continue
        if reachable is not None and rel[:-len(".smali")] not in reachable:
            continue
        stem = rel[:-len(".smali")]
        if "$" in stem:
            top, inner = stem.split("$", 1)
            enclosing, hint = _smali_meta(f)
            top_name = top.rsplit("/", 1)[-1]
            pkg = top.rsplit("/", 1)[0] if "/" in top else ""
            pkgs.setdefault(pkg, {}).setdefault(top_name, []).append(
                {"name": inner, "top": top_name,
                 "enclosing": enclosing, "type_hint": hint})
        else:
            pkg = stem.rsplit("/", 1)[0] if "/" in stem else ""
            pkgs.setdefault(pkg, {}).setdefault(stem.rsplit("/", 1)[-1], [])
    return [
        (pkg, {c: sorted(es, key=lambda e: e["name"]) for c, es in sorted(tops.items())})
        for pkg, tops in sorted(pkgs.items())
    ]


# ---------------------------------------------------------------- 组装 spec


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_spec(apk_path: Path, decoded: Path) -> dict:
    """从解包目录组装一份完整 spec（机器可推导部分，全部 disposition=confirm 待人确认）。"""
    apk_path = Path(apk_path)
    manifest_root = ET.parse(decoded / "AndroidManifest.xml").getroot()
    manifest = _parse_manifest(decoded)
    app_name = _app_label(manifest_root, decoded)

    resources = _scan_resources(decoded)

    # 自有代码包清单 {包路径: {顶层类: [内部类...]}}——提案展开逻辑类的依据。
    # 入口闭包过滤：混淆把库代码也搬进顶级短包，只收 manifest 入口可达的。
    # 入口只取**自有**组件——库组件（AdActivity/MultiDexApplication）会把
    # androidx 混淆短包（f0/r2/t2）带进闭包，那是库噪音不是游戏核心；
    # 全部组件都是库的极端壳工程才退回全量入口（宁收噪音不漏核心）。
    own_prefix = manifest["package"].replace(".", "/")
    all_entries = ([act["name"] for act in manifest["activities"]]
                   + ([manifest["application"]] if manifest["application"] else []))
    own_entries = [c for c in all_entries if _is_own_pkg(c.replace(".", "/"), own_prefix)]
    entries = own_entries or all_entries
    reachable = _own_reachable(decoded, entries, own_prefix)
    reachable_own = {c for c in reachable if _is_own_pkg(c, own_prefix)}
    own, lib = _code_stats(decoded, reachable_own)
    own_pkgs = _own_packages(decoded, reachable, own_prefix)
    # 顶层类 → (包路径, 内部类列表)，供 manifest 组件模块挂 inner_classes
    top_index: dict[str, tuple[str, list[dict]]] = {}
    for pkg, tops in own_pkgs:
        for top, entries in tops.items():
            top_index[f"{pkg.replace('/', '.')}.{top}" if pkg else top] = (pkg, entries)
    manifest_refs = {act["name"] for act in manifest["activities"]}
    if manifest["application"]:
        manifest_refs.add(manifest["application"])

    modules: list[dict] = []
    behaviors: list[dict] = []
    for act in manifest["activities"]:
        notes = [f"exported={act['exported'] or '未标注'}"]
        if act["orientation"]:
            notes.append(f"screenOrientation={act['orientation']}")
        if act["config_changes"]:
            notes.append(f"configChanges={act['config_changes']}")
        if act["has_launcher"]:
            notes.append("LAUNCHER 入口")
        if act["name"] in top_index:
            notes.append("自有代码（manifest 组件）")
        mod = {
            "name": _short_name(act["name"]),
            "source_ref": act["name"],
            "disposition": "confirm",
            "resources": [],
            "behaviors": [],
            "notes": "；".join(notes),
        }
        if act["name"] in top_index:
            mod["inner_classes"] = top_index[act["name"]][1]
        modules.append(mod)
        if act["has_launcher"]:
            behaviors.append(
                {
                    "screen": _short_name(act["name"]),
                    "trigger": "冷启动",
                    "expected": f"打开《{app_name}》，进入 {_short_name(act['name'])}",
                    "disposition": "confirm",
                    "notes": "由 LAUNCHER intent-filter 推导，细节待人工补充",
                }
            )

    # 非 manifest 的自有包：独立成模块（游戏核心常被混淆到顶级短包，如 w0）
    # manifest_refs 含 application 类——它另有"Application 全局入口"模块承载，
    # 不在包级模块里重复出现
    for pkg, tops in own_pkgs:
        dotted = pkg.replace("/", ".")
        # 已挂 manifest 组件模块的顶层类不重复建模块
        tops_rest = {c: es for c, es in tops.items()
                     if f"{dotted}.{c}" not in manifest_refs}
        if not tops_rest:
            continue
        n_cls = sum(1 + len(es) for es in tops_rest.values())
        mod = {
            "name": f"自有包 {dotted}（{len(tops_rest)} 顶层类/{n_cls} 含内部类）",
            "source_ref": dotted,
            "disposition": "confirm",
            "resources": [],
            "behaviors": [],
            "classes": sorted(tops_rest.keys()),
            "notes": "自有代码（smali 发现，非 manifest 组件；混淆短包名原样保留）",
        }
        entries = [e for es in tops_rest.values() for e in es]
        if entries:
            mod["inner_classes"] = entries
        modules.append(mod)

    if manifest["application"]:
        app_notes = [f"入口可达自有代码 {own} 类 / 库及不可达代码 {lib} 类"]
        if manifest["permissions"]:
            app_notes.append(
                "需要权限: " + ", ".join(manifest["permissions"]) + "（鸿蒙侧需对应申请）"
            )
        app_mod = {
            "name": "Application 全局入口",
            "source_ref": manifest["application"],
            "disposition": "confirm",
            "resources": [],
            "behaviors": [],
            "notes": "；".join(app_notes),
        }
        # 自有的 Application 子类：内部类挂到这个模块上（不另建包模块）
        if manifest["application"] in top_index:
            app_mod["inner_classes"] = top_index[manifest["application"]][1]
            app_mod["notes"] += "；自有代码（manifest 组件）"
        modules.append(app_mod)

    for i, m in enumerate(modules, 1):
        m_with_id = {"id": f"mod_{i:03d}", **m}
        modules[i - 1] = m_with_id
    for i, b in enumerate(behaviors, 1):
        b_with_id = {"id": f"beh_{i:03d}", **b}
        behaviors[i - 1] = b_with_id

    first_module = modules[0]["id"] if modules else "mod_001"
    spec = {
        "spec_version": SPEC_VERSION,
        "project": {
            "name": app_name,
            "source": str(apk_path),
            "target": "harmonyos-next",
            "created_at": _now(),
            "updated_at": _now(),
        },
        "resources": resources,
        "modules": modules,
        "behaviors": behaviors,
        "decisions": [],
        "build_log": [
            {
                "id": "log_001",
                "module_id": first_module,
                "action": "extracted",
                "summary": (
                    f"apktool 提取 {apk_path.name}：资源 {len(resources)} 项、"
                    f"模块 {len(modules)} 个、行为 {len(behaviors)} 条；"
                    f"入口可达自有代码 {own} 类 / 库及不可达 {lib} 类"
                ),
                "diff_ref": str(decoded),
                "at": _now(),
            }
        ],
        "seams": [],
    }
    return spec


# ---------------------------------------------------------------- 编排


def merge_manual_records(new_spec: dict, old_spec: dict | None) -> dict:
    """把旧 spec 里的人工记录（decisions/seams/build_log）合并进新 spec。

    机器推导部分（resources/modules/behaviors）以新的为准；人工产物一律保留。
    extract 重跑、extract 逻辑升级后重建，都走这个口子，保证不丢人的判断。
    """
    if not old_spec:
        return new_spec
    new_entry = new_spec["build_log"][0]
    new_spec["decisions"] = old_spec.get("decisions", [])
    new_spec["seams"] = old_spec.get("seams", [])
    # build_log 追加不清空；id 顺序重排（旧日志反复提取会攒下一堆 log_001）
    merged = list(old_spec.get("build_log", [])) + [new_entry]
    for i, e in enumerate(merged, 1):
        e["id"] = f"log_{i:03d}"
    new_spec["build_log"] = merged
    return new_spec


def rebuild_from_decoded(decoded: str | Path, old_spec: dict | None = None,
                         apk_name: str = "") -> dict:
    """从已解包目录重建 spec（免重跑 apktool；extract 逻辑升级后的补救入口）。

    decoded 目录里必须有 AndroidManifest.xml。old_spec 提供则合并人工记录。
    """
    decoded = Path(decoded)
    if not (decoded / "AndroidManifest.xml").exists():
        raise ExtractError(f"解包目录不完整（缺 AndroidManifest.xml）：{decoded}")
    apk = Path(apk_name or decoded.name)
    spec = build_spec(apk, decoded)
    return merge_manual_records(spec, old_spec)


def extract(
    apk_path: str | Path,
    spec_path: str | Path = "spec.json",
    workdir: str | Path | None = None,
    apktool_jar: str | None = None,
    java: str | None = None,
    no_decode: bool = False,
    force: bool = False,
) -> dict:
    """完整提取流程：解包 → 解析 → 组装 → 经 wbox.spec.save 落盘。返回 spec dict。"""
    apk = Path(apk_path)
    if not apk.exists():
        raise ExtractError(f"APK 不存在：{apk}")
    # 解包目录 ASCII 化（DevEco/hvigor 不认中文目录，2026-10-25 铁律）：
    # APK 名 "92934圆锯模拟器8.apk" → work/92934yuanjumoniqi8
    work = Path(workdir) if workdir else Path.cwd() / "work" / work_dir_name(apk.stem)

    if not no_decode:
        java_cmd, jar = _load_tool_config(apktool_jar, java)
        run_apktool(apk, work, java_cmd, jar)
    if not (work / "AndroidManifest.xml").exists():
        raise ExtractError(f"解包目录不完整（缺 AndroidManifest.xml）：{work}")

    spec = build_spec(apk, work)

    spec_file = Path(spec_path)
    if spec_file.exists():
        if not force:
            raise ExtractError(
                f"spec 已存在：{spec_file}；加 --force 才会重建"
                "（decisions / seams 会保留，build_log 追加不清空）"
            )
        spec = merge_manual_records(spec, load(spec_file))

    save(spec, spec_file)
    return spec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wbox-extract", description="阶段 1「拆」：APK → spec 草稿（资源/模块/行为骨架）"
    )
    parser.add_argument("apk", nargs="?", help="源 APK 路径（--rebuild-from 模式下可省略）")
    parser.add_argument("--spec", default="spec.json", help="输出 spec 路径（默认 ./spec.json）")
    parser.add_argument("--workdir", default=None, help="解包输出目录（默认 项目 work/<apk名>）")
    parser.add_argument("--apktool-jar", default=None, help="覆盖配置里的 apktool jar 路径")
    parser.add_argument("--java", default=None, help="覆盖 java 命令（默认 java）")
    parser.add_argument("--no-decode", action="store_true", help="跳过 apktool，直接解析已解包目录")
    parser.add_argument("--rebuild-from", default=None, metavar="DIR",
                        help="从已解包目录重建 spec（免重跑 apktool；人工记录保留）")
    parser.add_argument("--force", action="store_true", help="允许重建已存在的 spec（保留人工记录）")
    args = parser.parse_args(argv)

    try:
        if args.rebuild_from:
            spec_file = Path(args.spec)
            old = load(spec_file) if spec_file.exists() else None
            spec = rebuild_from_decoded(args.rebuild_from, old,
                                        apk_name=args.apk or "")
            save(spec, spec_file)
        elif args.apk:
            spec = extract(
                args.apk,
                spec_path=args.spec,
                workdir=args.workdir,
                apktool_jar=args.apktool_jar,
                java=args.java,
                no_decode=args.no_decode,
                force=args.force,
            )
        else:
            parser.error("要么给 apk，要么给 --rebuild-from DIR")
    except (ExtractError, SpecError) as exc:
        print(f"提取失败：{exc}", file=sys.stderr)
        return 1

    log = spec["build_log"][-1]
    print(f"提取完成 -> {args.spec}")
    print(f"  {log['summary']}")
    print(f"  应用：{spec['project']['name']}  来源：{spec['project']['source']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
