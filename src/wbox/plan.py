"""wbox.plan —— 阶段 2「画拼图」：spec 三段清单 → 鸿蒙结构提案。

定位（写死，不许绕）：
- 只生成"初稿"：确定性启发式映射（资源→rawfile 搬迁表、模块→logic/页面/组件
  划分、行为→页面/组件/对话框归并），供人工在 GUI 里逐条改。不猜玩法细节。
- 本模块顺带补上 extract 的已知缺陷：库资源（AndroidX/Material/Firebase/广告 SDK
  模板噪音）在此过滤，打上 drop 理由，不淹没游戏自有资产。
- 提案写回 spec["proposal"]（schema 已扩展），保存仍走 wbox.spec.save。

CLI：
    python -m wbox.plan spec.json            # 打印提案 JSON（不落盘）
    python -m wbox.plan spec.json --write    # 写回 spec["proposal"]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from wbox.ascii_names import ascii_name
from wbox.spec import load, save

# ---------------------------------------------------------------- 资源路由

# 库资源前缀黑名单（模板工程噪音；extract 不过滤，这里在提案层过滤）
_LIB_PREFIXES = (
    "abc_", "design_", "mtrl_", "m3_", "notification_", "preference_",
    "vector_", "common_google_", "common_full_open", "exo_", "media2_",
    "firebase_", "google_", "admob_", "unity", "applovin_", "unityads",
    "ic_ab_", "mtrl_", "tooltip_", "btn_", "ripple",
)

# 资源名 → rawfile 子目录（圆锯项目真实布局的推广规则；匹配前先把 \ 归一为 /）
_SUBDIR_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^logs?/"), "rawfile/logs"),
    (re.compile(r"^disks?/|^blade|/disk"), "rawfile/disks"),
    (re.compile(r"^particle/|\.particle$"), "rawfile/particle"),
    (re.compile(r"^model/|\.(json|glb|gltf|fnt)$"), "rawfile/model"),
    (re.compile(r"^sfx/|^sound|^bgm|\.(mp3|ogg|wav|m4a|flac)$"), "rawfile/sfx"),
    (re.compile(r"^ui/|^icon|^button|^menu|^dialog/|_icon|_button|_label"), "rawfile/ui"),
]

_FONT_EXT = {".ttf", ".otf", ".ttc", ".fnt"}

# 构建产物/库配置噪音（无扩展名的目录条目与 APK 结构残留）
_JUNK_NAMES = re.compile(
    r"^(meta-inf|attrs|bools|ids|public|styles|colors|dimens|arrays|plurals|"
    r".*multidex.*|androidsupport.*|.*\.version|.*crashlytics.*|com\..*|google\..*)$", re.I)


def _is_lib_resource(res: dict) -> bool:
    name = str(res.get("name", "")).lower()
    notes = str(res.get("notes", "")).lower()
    if any(name.startswith(p) for p in _LIB_PREFIXES):
        return True
    if "androidx" in notes or "material" in notes or "firebase" in notes:
        return True
    return False


def _is_junk(res: dict) -> bool:
    """无扩展名的目录条目 / APK 构建残留 / 库配置文件。"""
    name = str(res.get("name", "")).strip()
    if not name:
        return True
    if _JUNK_NAMES.match(name):
        return True
    norm = name.replace("\\", "/")
    stem = Path(norm).stem
    return "." not in stem and "/" not in norm


def _ascii_target(target: str) -> str:
    """rawfile 目标路径逐段 ASCII 化。

    2026-10-25 铁律：DevEco Studio 不识别中文目录/文件名——资源原名
    "圆锯.png" 进 rawfile 也必须叫 "yuanju.png"。原文件名在提案 name 字段
    保留，AI 生成代码只认 ASCII 目标，两边不会漂移。

    只化"含非 ASCII 字符"的段：纯 ASCII 段（logs/1/1.png 的 1、1.png）
    原样保留。曾对每段无差别 ascii_name，纯数字/短名触发兜底加哈希
    （1 → 1_c4ca），libGDX 侧 "logs/1/1.png" 引用全部错位，素材白搬。
    """
    return "/".join(
        seg if seg.isascii() else ascii_name(seg)
        for seg in str(target).split("/")
        if seg
    )


def _resource_target(res: dict) -> tuple[str, str, str]:
    """返回 (action, target, reason)。"""
    raw_name = str(res.get("name", ""))
    name = raw_name.replace("\\", "/")  # APK 扫描出的名字可能带反斜杠
    rtype = str(res.get("type", ""))
    fmt = str(res.get("format", ""))
    notes = str(res.get("notes", ""))
    # 构建期噪音：dexopt baseline profile / Capacitor 构建配置——H5 运行时不引用，
    # 搬进 rawfile 只是白占包体。
    if name.startswith("dexopt/") or name in ("capacitor.config.json", "capacitor.plugins.json"):
        return "drop", "", "构建期配置（dexopt baseline profile / Capacitor 构建配置），H5 运行时不引用"
    # Web 壳工程：assets/public/**（spec 里名作 public/**）整树进 rawfile，保 ./ 相对路径。
    # 必须排在字体/动画/配置等类型规则之前——H5 引用的 .woff2/.json/.js 是游戏本体
    # 资产，不是可弃的库配置；扁平化（圆锯工程那套）会让 index.html 的
    # "./assets/index-xxx.js" 全部断链 → 整包白屏。
    if name.startswith("public/"):
        rel = name[len("public/"):]
        if rel:
            return ("migrate", _ascii_target(f"rawfile/{rel}"),
                    "Web 壳工程：H5 资源整树进 rawfile，保 ./ 相对路径不断链")
    if _is_junk(res):
        return "drop", "", "构建产物/目录条目/库配置噪音，非游戏资产"
    if _is_lib_resource(res):
        return "drop", "", "库资源模板噪音（AndroidX/Material/广告 SDK 系），非游戏自有资产"
    if rtype == "font" or fmt in _FONT_EXT or Path(name).suffix.lower() in _FONT_EXT:
        return "drop", "", "位图/矢量字体改用系统字体（鸿蒙侧不搬字体文件，中文场景系统渲染更稳）"
    if rtype == "animation":
        return "drop", "", "Android 补间动画无对应物，鸿蒙侧用属性动画/Canvas 重做"
    if notes.startswith("res/") and rtype in ("config", "text"):
        return "drop", "", "Android res/ 配置（布局/取值/样式），鸿蒙侧按提案用 ArkTS 重写，不搬文件"
    for pattern, subdir in _SUBDIR_RULES:
        if pattern.search(name):
            # 保留子路径：logs/1/1.png → rawfile/logs/1/1.png
            rel = name.split("/", 1)[1] if "/" in name else Path(name).name
            if not rel:
                rel = Path(name).name
            return "migrate", _ascii_target(f"{subdir}/{rel}"), "按类型归入 rawfile 子目录（原名见 name 列）"
    if rtype in ("config", "level", "text"):
        return "migrate", _ascii_target(f"rawfile/{Path(name).name}"), "配置文件随包直用"
    return "migrate", _ascii_target(f"rawfile/ui/{Path(name).name}"), "图片资源默认进 rawfile/ui/"


# ---------------------------------------------------------------- 模块路由

# 库 / 广告 / 分析模块（不进入提案，转待裁决项）
_LIB_MODULE_RE = re.compile(
    r"(androidx\.|com\.google\.android\.gms|com\.google\.firebase|com\.google\.android\.material|"
    r"com\.unity3d|com\.applovin|"
    # Web 壳框架（Capacitor/Cordova）：游戏本体是 assets/public/ 下的 H5，
    # 这些类是安卓 WebView 外壳，鸿蒙侧由 ArkWeb + javaScriptProxy 承担。
    # 逐类迁移只会产出编译不过的僵尸文件（2026-10-26 跳石子工程实证：
    # 134 个框架类灌进 draft，靠删一行 layoutDirection 幻觉调用才编过）。
    r"com\.getcapacitor|getcapacitor|capacitor|com\.cordova|cordova|org\.apache\.cordova|"
    # 渠道/授权/计费壳：单机化默认剥除
    r"com\.android\.billingclient|com\.pairip|com\.dx\.|com\.unity\.tg|ddbgf)",
    re.I)
_AD_MODULE_RE = re.compile(r"(^ad|adactivity|admob|广告|banner|interstitial)", re.I)

# ---------------------------------------------------------------- Web 壳工程

# APK 的 assets/public/index.html（Capacitor/Cordova 打包产物）→ spec 资源名
# 归一化后作 "public/index.html"。命中即判定 Web 壳工程：游戏本体是 H5。
_WEB_SHELL_ENTRY_RE = re.compile(r"(^|/)public/index\.html$", re.I)


def _is_web_shell(spec: dict) -> bool:
    """spec.resources 里有 public/index.html 即 Web 壳工程。

    Capacitor/Cordova 把 Vite/Webpack 产物铺在 assets/public/ 下，原生层
    只有 BridgeActivity + WebView。此时逐类迁移框架代码是纯噪音。
    """
    for res in spec.get("resources", []):
        name = str(res.get("name", "")).replace("\\", "/")
        if _WEB_SHELL_ENTRY_RE.search(name):
            return True
    return False


def _web_shell_entry_module(spec: dict) -> dict:
    """找原版 WebView 宿主 Activity，作为容器三件套的 smali 参照。"""
    mods = spec.get("modules", [])
    for m in mods:
        if str(m.get("source_ref", "")).endswith("MainActivity"):
            return m
    for m in mods:
        if not _LIB_MODULE_RE.search(str(m.get("source_ref", ""))):
            return m
    return mods[0] if mods else {"id": "mod_001", "name": "", "source_ref": ""}


def _web_shell_container(entry: dict) -> list[dict]:
    """Web 壳工程的原生层三件套（写死，不随框架类数量膨胀）。"""
    mod_id = str(entry.get("id", "mod_001"))
    smali = _smali_rel(str(entry.get("source_ref", "")))
    return [
        {
            "mod_id": mod_id,
            "name": "EntryAbility",
            "target": "entryability/EntryAbility.ets",
            "pattern": "service",
            "reason": "Web 壳工程容器：原版 BridgeActivity 宿主 Activity 的窗口侧对应物"
                      "（沉浸全屏/隐藏系统栏/屏幕常亮/横屏锁定）。鸿蒙侧只此一个 Ability。",
            "smali": smali,
        },
        {
            "mod_id": mod_id,
            "name": "Index",
            "target": "pages/Index.ets",
            "pattern": "page",
            "reason": "Web 壳工程容器页：Web({src:$rawfile('index.html')}) 承载 H5 本体，"
                      "domStorageAccess(true) 开存档；唯一 @Entry 页面。",
            "smali": smali,
        },
        {
            "mod_id": mod_id,
            "name": "WebBridge",
            "target": "logic/WebBridge.ets",
            "pattern": "service",
            "reason": "Web 壳工程桥接：H5 的 navigator.vibrate 等 Web 能力经 "
                      "javaScriptProxy 落原生 vibrator。ArkWeb 无 androidBridge / "
                      "webkit.messageHandlers.bridge，不要伪造原生桥，H5 自走 web 降级。",
            "smali": smali,
        },
    ]


# 原版语义 → 鸿蒙模式（先中文提示，后英文类名；顺序即优先级）
_MODULE_RULES: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"(applicationlistener|listener|全局入口|根)", re.I), "service", "应用入口/生命周期根，鸿蒙侧 EntryAbility 初始化"),
    (re.compile(r"(数据表|实体数据|数值表|静态数据)", re.I), "state-store", "数据表/数值表，鸿蒙侧常量或 AppStorage"),
    (re.compile(r"(屏|screen|activity|launcher)", re.I), "page", "原版屏幕/入口，鸿蒙侧页面"),
    (re.compile(r"(演员|实体|原木|角色|敌人|物品|粒子|actor|entity|sprite|body)", re.I), "component", "自绘实体/视图单元，鸿蒙侧组件"),
    (re.compile(r"(对话|弹窗|dialog|popup)", re.I), "dialog", "弹窗类，鸿蒙侧自定义对话框"),
    (re.compile(r"(音频|audio|sound|music|player|sfx)", re.I), "service", "音频服务，鸿蒙侧 AVPlayer 池化"),
    (re.compile(r"(存档|持久|persist|storage|prefs|save)", re.I), "persistence", "持久化，鸿蒙侧 Preferences"),
    (re.compile(r"(状态|数据|配置|state|store|data|config|settings)", re.I), "state-store", "共享状态/数据表，鸿蒙侧 AppStorage 中央状态"),
    (re.compile(r"(组件|ui层|component|widget)", re.I), "component", "UI 组件层，鸿蒙侧自定义组件"),
    (re.compile(r"(util|helper|math|economy|logic|core|engine|游戏|game)", re.I), "pure-logic", "纯计算/数值逻辑，原样搬公式"),
]

_PATTERN_DIR = {
    "page": "pages",
    "component": "components",
    "dialog": "dialogs",
    "state-store": "logic",
    "pure-logic": "logic",
    "persistence": "logic",
    "service": "logic",
}

# 继承线索专用规则：混淆类名（$a/$b）没有语义，但 .super/.implements 有。
# 不能直接套 _MODULE_RULES——"listener"会把 scene2d ClickListener 错判成
# 应用生命周期根（service），它明明是 UI 输入单元。
_HINT_RULES: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"(badlogic\.gdx\.Screen|GameScreen)", re.I), "page",
     "libGDX Screen 实现（游戏屏），鸿蒙侧页面"),
    (re.compile(r"(ClickListener|InputListener|ChangeListener|Actor|Group|Stage|"
                r"Button|Label|Image|View|Widget|Dialog|OnClickListener|"
                r"OnCancelListener|OnDismissListener)", re.I), "component",
     "UI 单元/事件监听（scene2d/视图系父类），鸿蒙侧组件"),
    (re.compile(r"(ApplicationListener)", re.I), "service",
     "应用入口/生命周期根，鸿蒙侧 EntryAbility 初始化"),
    (re.compile(r"(Audio|Sound|Music|Player|Sfx)", re.I), "service",
     "音频服务，鸿蒙侧 AVPlayer 池化"),
]


def _classify_hint(hint: str) -> tuple[str, str] | None:
    """按继承线索判定模式；不命中返回 None（调用方保持纯逻辑默认）。"""
    for pattern, kind, reason in _HINT_RULES:
        if pattern.search(str(hint)):
            return kind, reason
    return None


def _pascal(name: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", name)
    return "".join(p[:1].upper() + p[1:] for p in parts if p) or "Module"


def _class_name(source_ref: str) -> str:
    """从 source_ref 提取类名并 Pascal 化（兼容 obfuscated 的 a/b 形式与 .smali 后缀）。"""
    ref = str(source_ref or "")
    first = re.split(r"[,+;]", ref)[0].strip()
    if first.lower().endswith(".smali"):
        first = first[:-6]
    seg = re.split(r"[./\\]", first)[-1]
    return _pascal(seg)


def _smali_rel(dotted: str) -> str:
    """类全限定名（点分）→ smali 相对路径（斜杠 + $ 保留）。

    "com.dim.circularsaw.AndroidLauncher$b" → "com/dim/circularsaw/AndroidLauncher$b"
    "w0/g$b"（已是斜杠形式）原样返回。任务包按此路径收集 smali 参考。
    """
    s = str(dotted or "")
    if "/" in s and "\\" not in s:
        return s
    return s.replace("\\", "/").replace(".", "/")


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _cjk_key(text: str) -> str:
    """取前两个汉字作为屏名匹配键（"车间屏"→"车间"，"游戏屏"→"游戏"）。"""
    cjk = [ch for ch in str(text) if "\u4e00" <= ch <= "\u9fff"]
    return "".join(cjk[:2])


def _module_target(mod: dict, pattern: str, index: int) -> str:
    """目标文件路径：中文名用 source_ref 类名，保证路径 ASCII 且不撞车。"""
    name = str(mod.get("name", ""))
    ref = str(mod.get("source_ref", ""))
    base = _class_name(ref) if _has_cjk(name) else _pascal(name)
    if not base or base == "Module":
        base = f"Module{index}"
    directory = _PATTERN_DIR[pattern]
    if pattern == "page":
        return f"{directory}/{base}Page.ets"
    return f"{directory}/{base}.ets"


def _classify_module(mod: dict) -> tuple[str, str]:
    text = f"{mod.get('name', '')} {mod.get('source_ref', '')}"
    # 内部类/匿名类（$ 形式）是逻辑单元，不是页面——名字里带外层类名
    # （如 AndroidLauncher$b）会误命中"屏幕/入口"规则，先短路
    if "$" in text:
        return "pure-logic", "内部类/匿名类，独立逻辑单元"
    for pattern, kind, reason in _MODULE_RULES:
        if pattern.search(text):
            return kind, reason
    return "pure-logic", "未匹配已知模式，暂归纯逻辑类，人工复核"


# ---------------------------------------------------------------- 行为归并

_DIALOG_HINTS = re.compile(r"(结算|选择|对话|弹窗|dialog|well.?done|select)", re.I)


def _ui_units(behaviors: list[dict], modules: list[dict]) -> list[dict]:
    """行为按屏归并成 UI 单元；中文屏名借模块 source_ref 类名保证路径 ASCII 唯一。"""
    by_screen: dict[str, list[dict]] = {}
    for b in behaviors:
        screen = str(b.get("screen", "未命名屏"))
        by_screen.setdefault(screen, []).append(b)
    units: list[dict] = []
    for idx, (screen, members) in enumerate(sorted(by_screen.items()), start=1):
        kind = "dialog" if _DIALOG_HINTS.search(screen) else "page"
        # 找名字里含该屏名的模块，借它的类名；找不到用序号兜底
        key = _cjk_key(screen) if _has_cjk(screen) else screen
        base = ""
        for m in modules:
            mname = str(m.get("name", ""))
            if key and key in mname:
                base = _class_name(str(m.get("source_ref", "")))
                break
        if not base:
            base = f"Screen{idx}"
        target = f"{_PATTERN_DIR[kind]}/{base}{'Dialog' if kind == 'dialog' else 'Page'}.ets"
        units.append({
            "screen": screen,
            "kind": kind,
            "target": target,
            "beh_ids": [str(m.get("id", "")) for m in members],
            "reason": f"{len(members)} 条行为归并到同一屏（原版同屏行为，鸿蒙侧同页面承载）"
                      + ("" if not _has_cjk(screen) else "；屏名为中文，路径借用原类名，可人工改"),
        })
    return units


# ---------------------------------------------------------------- 主入口


def generate_proposal(spec: dict) -> dict:
    """从 spec 生成提案 dict（不落盘）。"""
    resource_moves = []
    for res in spec.get("resources", []):
        action, target, reason = _resource_target(res)
        resource_moves.append({
            "res_id": str(res.get("id", "")),
            "name": str(res.get("name", "")),
            "action": action,
            "target": target,
            "reason": reason,
        })

    # 模块去重（同 source_ref 只留首条）+ 排除库/广告模块（转待裁决）
    logic_classes = []
    excluded: list[str] = []
    seen_refs: set[str] = set()
    for idx, mod in enumerate(spec.get("modules", []), start=1):
        ref = str(mod.get("source_ref", "")).strip()
        name = str(mod.get("name", ""))
        if ref and ref in seen_refs:
            continue  # 深挖派生条目与 manifest 条目重复
        if ref:
            seen_refs.add(ref)
        if _LIB_MODULE_RE.search(ref) or _LIB_MODULE_RE.search(name):
            excluded.append(str(mod.get("id", "")))
            continue
        if _AD_MODULE_RE.search(name) or _AD_MODULE_RE.search(ref):
            excluded.append(str(mod.get("id", "")))
            continue
        pkg_classes = [str(c) for c in (mod.get("classes") or []) if str(c).strip()]
        # 包级模块（混淆短包聚合，如"自有包 w0"）本身不是类：source_ref 是
        # 包路径，没有对应 smali 文件——模块级条目跳过，只展开其顶层类与
        # 内部类（w0.g 这类游戏核心全在这一层，漏了就是漏整个游戏）。
        if not pkg_classes:
            pattern, reason = _classify_module(mod)
            logic_classes.append({
                "mod_id": str(mod.get("id", "")),
                "name": name,
                "target": _module_target(mod, pattern, idx),
                "pattern": pattern,
                "reason": reason,
                "smali": _smali_rel(ref),
            })
        ref_cls = _class_name(ref)
        # 包级模块的顶层类：各自展开为独立逻辑类（w0.g 是 libGDX 主类，
        # 藏在混淆短包里，只展开内部类会整个漏掉游戏核心）
        for cls in pkg_classes:
            cls_name = f"{ref_cls}.{cls}"
            cls_mod = {"name": cls_name, "source_ref": f"{ref}.{cls}"}
            cpattern, creason = _classify_module(cls_mod)
            logic_classes.append({
                "mod_id": str(mod.get("id", "")),
                "name": cls_name,
                "target": _module_target(cls_mod, cpattern, idx),
                "pattern": cpattern,
                "reason": creason,
                "smali": _smali_rel(f"{ref}/{cls}"),
            })
        # 内部类展开：libGDX 壳游戏的逻辑大量藏在匿名/内部类里，
        # 各自是独立重做单元，必须成为独立逻辑类条目。
        # 内部类独立分类（不继承外层 pattern）——$a/$b/$c 这类名字没有
        # 页面语义，硬继承会把逻辑类错成 *Page.ets。
        # smali 元信息（外壳方法/继承线索）进 reason，供人工与 AI 判断职责。
        for entry in mod.get("inner_classes") or []:
            inner = str(entry.get("name", "")) if isinstance(entry, dict) else str(entry)
            if not inner:
                continue
            top = str(entry.get("top", "")) if isinstance(entry, dict) else ""
            # 归属命名：manifest 组件的 ref 即顶层类时不重复；包级模块带顶层类
            inner_name = (f"{ref_cls}${inner}" if top == ref_cls or not top
                          else f"{ref_cls}.{top}${inner}")
            inner_mod = {"name": inner_name, "source_ref": f"{ref}${inner}"}
            ipattern, ireason = _classify_module(inner_mod)
            # 继承线索升级判定：混淆名没有语义，但 .super/.implements 有——
            # 继承 scene2d Actor/ClickListener 的是 UI 组件，别默认 pure-logic
            if isinstance(entry, dict) and entry.get("type_hint"):
                hit = _classify_hint(str(entry["type_hint"]))
                if hit:
                    ipattern, ireason = hit[0], f"按继承线索判定：{hit[1]}"
            if isinstance(entry, dict) and (entry.get("enclosing") or entry.get("type_hint")):
                bits = []
                if entry.get("enclosing"):
                    bits.append(f"外壳方法 {entry['enclosing']}()")
                if entry.get("type_hint"):
                    bits.append(f"继承/实现 {entry['type_hint']}")
                ireason = f"{ireason}（{'；'.join(bits)}）"
            logic_classes.append({
                "mod_id": str(mod.get("id", "")),
                "name": inner_name,
                "target": _module_target(inner_mod, ipattern, idx),
                "pattern": ipattern,
                "reason": ireason,
                # manifest 组件的 ref 即顶层类（com.x.Y），内部类直接 $ 拼接；
                # 包级模块的 ref 是包路径（w0），才需要 ref/top$inner
                "smali": _smali_rel(
                    f"{ref}${inner}" if (top == ref_cls or not top)
                    else f"{ref}/{top}${inner}"
                ),
            })

    ui_units = _ui_units(spec.get("behaviors", []), spec.get("modules", []))

    # Web 壳工程：把提案裁到容器三件套。必须放在模块展开之后——展开结果仍要
    # 照走一遍，excluded 才能数清被排除的框架类数量，写进开放问题里。
    web_shell = _is_web_shell(spec)
    if web_shell:
        entry = _web_shell_entry_module(spec)
        logic_classes = _web_shell_container(entry)
        ui_units = [{
            "screen": "Web 容器（H5 本体）",
            "kind": "page",
            "target": "pages/Index.ets",
            "beh_ids": [],
            "reason": "Web 壳工程：原版所有屏都在 H5 内，鸿蒙侧只有一个容器页",
        }]

    # 待人工裁决项：全部 confirm 处置 + 结构性取舍
    open_questions: list[dict] = []
    if web_shell:
        open_questions.append({
            "topic": f"Web 壳工程（Capacitor/Cordova）：游戏本体是 assets/public/ 下的 H5，"
                     f"{len(excluded)} 个框架/渠道类不迁移，原生层只需容器三件套",
            "related": excluded[:50],
            "why": "H5 自带 web 降级（Preferences→localStorage、Haptics→navigator.vibrate、"
                   "IAP→mock），鸿蒙侧不接 Capacitor/Cordova 框架；如确需原生能力请登记 seam",
        })
    confirm_res = [r.get("id") for r in spec.get("resources", []) if r.get("disposition") == "confirm"]
    if confirm_res:
        open_questions.append({
            "topic": f"{len(confirm_res)} 个资源处置待确认（原 disposition=confirm）",
            "related": [str(i) for i in confirm_res],
            "why": "机器无法判断这些资源是否游戏自有资产，需人工过目",
        })
    dropped = [m for m in resource_moves if m["action"] == "drop"]
    if dropped:
        lib_n = sum(1 for m in dropped if "库资源" in m["reason"])
        if lib_n:
            open_questions.append({
                "topic": f"过滤掉 {lib_n} 个库资源（AndroidX/Material/广告 SDK 模板噪音）",
                "related": [m["res_id"] for m in dropped if "库资源" in m["reason"]][:50],
                "why": "extract 不过滤库资源，提案层按前缀黑名单过滤；若误杀自有资产请改回 migrate",
            })
    if excluded:
        open_questions.append({
            "topic": f"{len(excluded)} 个库/广告模块不进入提案（AndroidX/GMS/广告 SDK）",
            "related": excluded,
            "why": "单机化迁移不接第三方 SDK；如确需保留（如登录/支付）请人工改回并登记 seam",
        })
    for mod in spec.get("modules", []):
        notes = str(mod.get("notes", ""))
        if "screenOrientation" in notes:
            open_questions.append({
                "topic": f"{mod.get('name')} 屏幕方向策略（{notes.split('screenOrientation=')[-1].split('；')[0]}）",
                "related": [str(mod.get("id", ""))],
                "why": "原版锁定方向，鸿蒙侧需决定跟随系统还是锁定横屏",
            })
            break

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "web_shell": web_shell,
        "resource_moves": resource_moves,
        "logic_classes": logic_classes,
        "ui_units": ui_units,
        "open_questions": open_questions,
    }


def apply_proposal(spec_path: str | Path) -> dict:
    """生成提案并写回 spec["proposal"]（经 wbox.spec.save）。"""
    spec = load(spec_path)
    spec["proposal"] = generate_proposal(spec)
    save(spec, spec_path)
    return spec["proposal"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="画拼图：spec → 鸿蒙结构提案")
    parser.add_argument("spec", help="spec.json 路径")
    parser.add_argument("--write", action="store_true", help="写回 spec['proposal']")
    args = parser.parse_args(argv)

    if args.write:
        p = apply_proposal(args.spec)
        print(f"提案已写回 {args.spec}")
    else:
        p = generate_proposal(load(args.spec))
    mig = sum(1 for m in p["resource_moves"] if m["action"] == "migrate")
    drop = sum(1 for m in p["resource_moves"] if m["action"] == "drop")
    if p.get("web_shell"):
        print("[Web 壳工程] 游戏本体是 assets/public/ 下的 H5，原生层只需容器三件套；"
              "框架类不迁移。")
    print(f"资源搬迁 {mig} 项 / 丢弃 {drop} 项；逻辑类 {len(p['logic_classes'])} 个；"
          f"UI 单元 {len(p['ui_units'])} 个；待裁决 {len(p['open_questions'])} 项")
    print(json.dumps(p, ensure_ascii=False, indent=2)[:1500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
