"""wbox.gui.panels.resource_explorer —— 「资源」栏：自动分类 + 搜索 + 图片预览。

存在理由（用户需求：把"文件夹那个地方更细致"）：原先资源栏只是 spec.resources 的
一层平铺树，几百项混在一起，既看不出哪类是图、哪类是配置，也点不开图。
本面板做三件事：

1. **自动分类**：按扩展名 + 路径特征把资源归入 图片/音频/字体/布局与配置/代码/
   着色器/其它。规则集中在 RESOURCE_CATEGORIES 一个常量里，加新格式只改这一处。
2. **实时搜索**：按名称 / 相对路径 / 用途过滤，命中即高亮分组计数。
3. **双击看实物**：图片开预览窗（尺寸/体积/路径/决策），文本开内置查看器，
   其它走系统关联程序。

数据源仍然是 spec.resources（经 wbox.gui.session），不新造任何数据源。
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from wbox.gui.panels.image_preview import ImagePreviewDialog
from wbox.gui.session import ProjectSession
from wbox.gui import theme
from wbox.gui.uikit import harden_window, plain_text

# ---------------------------------------------------------------- 分类规则
# 唯一需要扩展的地方：加新格式 = 往对应集合里加一个后缀或路径关键字。
# 结构：分类名 -> (说明, 后缀集合, 路径关键字集合)
RESOURCE_CATEGORIES: dict[str, tuple[str, frozenset[str], frozenset[str]]] = {
    "图片": (
        "位图与矢量图：PNG/JPG/WEBP/GIF/SVG，迁移时主要看分辨率与透明通道",
        frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg", ".9.png", ".ico"}),
        frozenset({"/drawable", "/mipmap", "/drawable-", "/mipmap-", "/images/", "/img/"}),
    ),
    "音频": (
        "音效与音乐：MP3/OGG/WAV/M4A，鸿蒙侧需确认播放器与格式支持",
        frozenset({".mp3", ".ogg", ".wav", ".m4a", ".flac", ".aac", ".mid", ".midi"}),
        frozenset({"/raw/", "/sfx/", "/sound/", "/audio/", "/music/"}),
    ),
    "字体": (
        "字体文件：TTF/OTF，注意体积与子集化，鸿蒙 rawfile 直装",
        frozenset({".ttf", ".otf", ".ttc", ".woff", ".woff2"}),
        frozenset({"/font", "/fonts/"}),
    ),
    "布局与配置": (
        "XML/JSON 等配置与布局：菜单、动画、颜色、尺寸定义",
        frozenset({".xml", ".json", ".json5", ".yml", ".yaml", ".properties", ".cfg", ".ini"}),
        frozenset({"/layout", "/values", "/menu", "/anim", "/animator", "/xml/", "/config"}),
    ),
    "代码": (
        "可执行形态的代码：smali/dex/js/lua，迁移重点是逻辑对齐而非直搬",
        frozenset({".smali", ".dex", ".js", ".lua", ".py", ".so", ".jar", ".class"}),
        frozenset({"/smali", "/smali_classes", "/lib/", "/jniLibs/"}),
    ),
    "着色器": (
        "着色器与特效脚本：glsl/hlsl/frag/vert，鸿蒙侧需换成 ArkGraphics 能力",
        frozenset({".glsl", ".hlsl", ".frag", ".vert", ".shader", ".fsh", ".vsh"}),
        frozenset({"/shader", "/shaders/"}),
    ),
    "其它": (
        "未归入上述分类的资源：二进制数据、数据库、证书等",
        frozenset(),
        frozenset(),
    ),
}

# spec.resource_type → 兜底分类（当扩展名/路径都判不出来时用）
_TYPE_FALLBACK: dict[str, str] = {
    "image": "图片", "audio": "音频", "font": "字体", "level": "布局与配置",
    "config": "布局与配置", "animation": "布局与配置", "text": "布局与配置",
}

# spec.disposition → 中文决策（迁移/弃/待裁决一目了然）
_DISPOSITION_CN: dict[str, str] = {
    "reuse": "复用", "convert": "转换", "rewrite": "重写",
    "replace": "替代", "confirm": "待裁决",
}
_DISPOSITION_COLOR: dict[str, str] = {
    "reuse": "C_SUCCESS_TXT", "convert": "C_INFO_TXT", "rewrite": "C_WARNING_TXT",
    "replace": "C_WARNING_TXT", "confirm": "C_DANGER_TXT",
}

_IMAGE_SUFFIXES = RESOURCE_CATEGORIES["图片"][1]
_TEXT_SUFFIXES = frozenset({".xml", ".json", ".json5", ".txt", ".smali", ".js",
                            ".yml", ".yaml", ".properties", ".cfg", ".ini", ".md"})
# 5 列塞进 320px 的左栏会把文件名压成省略号，所以只留 4 列：
# 「类型」由分类分组本身表达（组名就是类型），完整字段在下方详情与 tooltip 里。
_COLUMNS = ["名称", "大小", "决策", "相对路径"]
_COL_STRETCH = {0, 3}       # 名称与路径吃剩余宽度，其余能窄则窄
_COL_NAME, _COL_SIZE, _COL_DISP, _COL_PATH = range(4)

_INDEX_MAX_FILES = 20000    # 路径索引上限：超大工程不至于卡住刷新


def classify(name: str, rel_path: str, res_type: str = "") -> str:
    """判定资源分类：扩展名 → 路径特征 → spec.type 兜底 → 其它。"""
    ext = Path(rel_path or name).suffix.lower()
    lowered = (rel_path or name).replace("\\", "/").lower()
    for cat, (_desc, exts, hints) in RESOURCE_CATEGORIES.items():
        if cat == "其它":
            continue
        if ext in exts:
            return cat
        for hint in hints:
            if hint in lowered:
                return cat
    fallback = _TYPE_FALLBACK.get(str(res_type or "").strip().lower())
    return fallback or "其它"


def _fmt_size(n: int | float | None) -> str:
    try:
        size = int(n or 0)
    except (TypeError, ValueError):
        return "—"
    if size <= 0:
        return "—"
    if size >= 1024 * 1024:
        return f"{size / 1048576:.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


class ResourceExplorerPanel(QWidget):
    """资源栏主体：分类树 + 搜索 + 双击预览 + 详情。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session: ProjectSession | None = None
        self._index: dict[str, list[Path]] | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索资源：名称 / 路径 / 用途…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        lay.addWidget(self.search)

        self.count_label = QLabel("（未打开工程）")
        self.count_label.setObjectName("muted")
        lay.addWidget(self.count_label)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(_COLUMNS)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionBehavior(QTreeWidget.SelectionBehavior.SelectRows)
        self.tree.setUniformRowHeights(False)
        self.tree.setWordWrap(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.currentItemChanged.connect(self._show_detail)
        header = self.tree.header()
        header.setMinimumSectionSize(52)
        for c in range(len(_COLUMNS)):
            mode = header.ResizeMode.Stretch if c in _COL_STRETCH else header.ResizeMode.ResizeToContents
            header.setSectionResizeMode(c, mode)
        lay.addWidget(self.tree, stretch=1)

        self.detail = QLabel("选中资源后显示完整信息")
        self.detail.setObjectName("muted")
        self.detail.setMinimumHeight(76)
        lay.addWidget(self.detail)

        harden_window(self)

    # ------------------------------------------------------------ 数据

    def refresh(self, session: ProjectSession) -> None:
        self._session = session
        self._index = None          # 换工程/换 spec 后索引作废
        self._rebuild()
        self._apply_filter(self.search.text())

    def _rebuild(self) -> None:
        self.tree.clear()
        session = self._session
        if session is None:
            self.count_label.setText("（未打开工程）")
            return
        items: list[dict] = list(session.resources)
        buckets: dict[str, list[dict]] = {}
        for res in items:
            rel = str(res.get("notes") or "")
            cat = classify(str(res.get("name") or res.get("id") or ""), rel,
                           str(res.get("type") or ""))
            buckets.setdefault(cat, []).append(res)

        total = len(items)
        self.count_label.setText(f"共 {total} 项资源，按类型自动分为 {len(buckets)} 类")
        self.count_label.setToolTip(self.count_label.text())

        for cat in list(RESOURCE_CATEGORIES) + [c for c in buckets if c not in RESOURCE_CATEGORIES]:
            members = buckets.get(cat)
            if not members:
                continue
            desc = RESOURCE_CATEGORIES.get(cat, (cat, frozenset(), frozenset()))[0]
            root = QTreeWidgetItem([f"{cat}（{len(members)}）", "", "", "", desc])
            root.setFlags(root.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            root.setToolTip(0, f"{cat}：{desc}")
            self.tree.addTopLevelItem(root)
            for res in sorted(members, key=lambda r: str(r.get("name") or "")):
                child = self._make_item(res)
                root.addChild(child)
            root.setExpanded(True)
        self.tree.expandToDepth(0)

    def _make_item(self, res: dict) -> QTreeWidgetItem:
        name = str(res.get("name") or res.get("id") or "")
        rel = str(res.get("notes") or "")
        disp = str(res.get("disposition") or "")
        child = QTreeWidgetItem([
            name,
            _fmt_size(res.get("size_bytes")),
            _DISPOSITION_CN.get(disp, disp),
            rel,
        ])
        child.setData(0, Qt.ItemDataRole.UserRole, res)
        tooltip = "\n".join(x for x in (
            name, rel, str(res.get("usage") or ""),
            f"类型：{res.get('type', '')}　格式：{res.get('format', '')}") if x)
        for c in range(len(_COLUMNS)):
            text = plain_text(child.text(c))
            if text:
                child.setToolTip(c, tooltip if c == 0 else text)
        if disp in _DISPOSITION_COLOR:
            child.setForeground(_COL_DISP, QColor(getattr(theme, _DISPOSITION_COLOR[disp])))
        return child

    # ------------------------------------------------------------ 过滤

    def _apply_filter(self, text: str) -> None:
        keyword = (text or "").strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            root = self.tree.topLevelItem(i)
            visible = 0
            for j in range(root.childCount()):
                child = root.child(j)
                res = child.data(0, Qt.ItemDataRole.UserRole) or {}
                hay = " ".join([
                    str(res.get("name") or ""), str(res.get("notes") or ""),
                    str(res.get("usage") or ""), str(res.get("id") or ""),
                    str(res.get("type") or ""),
                ]).lower()
                hit = (not keyword) or (keyword in hay)
                child.setHidden(not hit)
                visible += int(hit)
            root.setHidden(visible == 0)
            label = root.text(0).split("（")[0]
            root.setText(0, f"{label}（{visible}）")

    def _show_detail(self, current: QTreeWidgetItem | None, _prev=None) -> None:
        if current is None:
            self.detail.setText("选中资源后显示完整信息")
            return
        res = current.data(0, Qt.ItemDataRole.UserRole)
        if not res:
            self.detail.setText("选中资源后显示完整信息")
            return
        rel = str(res.get("notes") or "")
        real = self._resolve(rel)
        disp = str(res.get("disposition") or "")
        color = getattr(theme, _DISPOSITION_COLOR.get(disp, "C_FG"))
        lines = [
            f"<b>{res.get('name') or res.get('id')}</b> "
            f"<span style='color:{color}'>（{_DISPOSITION_CN.get(disp, disp or '未决')}）</span>",
            f"<span style='color:{theme.C_FG_MUTED}'>ID：</span>{res.get('id', '')}"
            f"　<span style='color:{theme.C_FG_MUTED}'>类型：</span>{res.get('type', '')}"
            f"　<span style='color:{theme.C_FG_MUTED}'>格式：</span>{res.get('format', '')}"
            f"　<span style='color:{theme.C_FG_MUTED}'>大小：</span>{_fmt_size(res.get('size_bytes'))}",
            f"<span style='color:{theme.C_FG_MUTED}'>用途：</span>{res.get('usage', '') or '—'}",
            f"<span style='color:{theme.C_FG_MUTED}'>相对路径：</span>{rel or '—'}",
        ]
        if real is not None:
            lines.append(f"<span style='color:{theme.C_FG_MUTED}'>磁盘位置：</span>{real}")
        else:
            lines.append("<span style='color:" + theme.C_FG_MUTED + "'>磁盘位置：</span>"
                         "（未在拆解目录中找到，可能该资源已不在 work/ 下）")
        self.detail.setText("<br>".join(lines))
        self.detail.setToolTip(plain_text(self.detail.text()))

    # ------------------------------------------------------------ 路径解析

    def _candidate_roots(self) -> list[Path]:
        session = self._session
        if session is None:
            return []
        roots: list[Path] = [session.work_dir, session.project_dir]
        try:
            for sub in session.work_dir.iterdir():
                if sub.is_dir():
                    roots.append(sub)
        except OSError:
            pass
        return roots

    def _resolve(self, rel: str) -> Path | None:
        """把 spec 里的相对路径解析成磁盘真实路径（失败再按文件名索引兜底）。"""
        if not rel:
            return None
        rel_clean = rel.replace("\\", "/").lstrip("/")
        for root in self._candidate_roots():
            cand = root / rel_clean
            if cand.is_file():
                return cand
        index = self._index or self._build_index()
        hits = index.get(Path(rel_clean).name.lower()) or []
        return hits[0] if hits else None

    def _build_index(self) -> dict[str, list[Path]]:
        """按文件名建索引（懒建、有上限），用于 spec 路径与磁盘布局不一致时兜底。"""
        index: dict[str, list[Path]] = {}
        scanned = 0
        for root in self._candidate_roots():
            if not root.is_dir():
                continue
            try:
                for p in root.rglob("*"):
                    scanned += 1
                    if scanned > _INDEX_MAX_FILES:
                        break
                    if p.is_file():
                        index.setdefault(p.name.lower(), []).append(p)
            except OSError:
                continue
            if scanned > _INDEX_MAX_FILES:
                break
        self._index = index
        return index

    # ------------------------------------------------------------ 打开

    def _on_double_click(self, item: QTreeWidgetItem, _column: int) -> None:
        res = item.data(0, Qt.ItemDataRole.UserRole)
        if not res:
            return
        rel = str(res.get("notes") or "")
        real = self._resolve(rel)
        if real is None:
            QMessageBox.information(
                self, "找不到文件",
                f"未在拆解目录中找到该资源：\n{rel or '(spec 未记录路径)'}\n\n"
                f"可先在「① 拆」步重新拆解，或用「文件」tab 手工定位。")
            return
        self.open_path(real)

    def open_path(self, path: Path) -> None:
        """按类型路由打开：图片 → 预览窗；文本 → 内置查看器；其余 → 系统关联。"""
        suffix = path.suffix.lower()
        try:
            if suffix in _IMAGE_SUFFIXES:
                ImagePreviewDialog(path, self).exec()
            elif suffix in _TEXT_SUFFIXES:
                from wbox.gui.panels.files import TextViewerDialog

                TextViewerDialog(path, self).exec()
            else:
                if not QDesktopServices.openUrl(path.as_uri()):
                    QMessageBox.information(self, "无法打开", f"没有能打开 {path.name} 的关联程序")
        except OSError as e:
            QMessageBox.warning(self, "打开失败", str(e))

    # ------------------------------------------------------------ 右键菜单

    def _menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        res = item.data(0, Qt.ItemDataRole.UserRole)
        if not res:
            return
        real = self._resolve(str(res.get("notes") or ""))
        menu = QMenu(self)
        if real is not None and real.suffix.lower() in _IMAGE_SUFFIXES:
            act = menu.addAction("预览图片…")
            act.triggered.connect(lambda _c=False: self.open_path(real))
        else:
            act = menu.addAction("打开")
            act.setEnabled(real is not None)
            act.triggered.connect(lambda _c=False: self.open_path(real))
        act_copy = menu.addAction("复制相对路径")
        act_copy.triggered.connect(lambda _c=False: self._copy(str(res.get("notes") or "")))
        if real is not None:
            act_path = menu.addAction("复制磁盘路径")
            act_path.triggered.connect(lambda _c=False: self._copy(str(real)))
            act_reveal = menu.addAction("在资源管理器中显示")
            act_reveal.triggered.connect(
                lambda _c=False: QDesktopServices.openUrl(real.parent.as_uri()))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    @staticmethod
    def _copy(text: str) -> None:
        QApplication.clipboard().setText(text)

    # ------------------------------------------------------------ 分类扩展（供外部调用）

    @staticmethod
    def categories() -> dict[str, tuple[str, frozenset[str], frozenset[str]]]:
        """暴露分类规则（诊断/统计复用同一份真相）。"""
        return dict(RESOURCE_CATEGORIES)

    @staticmethod
    def match_glob(path: str, pattern: str) -> bool:
        return fnmatch.fnmatch(path.replace("\\", "/").lower(), pattern.lower())
