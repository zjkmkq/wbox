"""wbox.gui.panels.inventory —— 左栏：文件 / 资源 / 模块 / 行为 四段清单。

文件 tab：直接浏览工程目录，双击打开拆解产物（文本走内置查看器、图片走预览窗、
其余走系统程序）。
资源 tab（2026-10-27 大改）：改为 ResourceExplorerPanel —— 自动分类 + 实时搜索
+ 双击看图 + 每项显示相对路径/大小/类型/迁移决策。
模块/行为 tab：维持 spec 清单只读浏览。

所有表格统一走 uikit.configure_table（长列 Stretch、短列 ResizeToContents、
单元格 tooltip 全文），杜绝"字被遮挡"。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from wbox.gui.panels.files import FileBrowserPanel
from wbox.gui.panels.resource_explorer import ResourceExplorerPanel
from wbox.gui.session import ProjectSession
from wbox.gui import theme
from wbox.gui.uikit import harden_window, plain_text

# spec.disposition 真实枚举：reuse/convert/rewrite/replace/confirm
_DISP_CN = {
    "reuse": "复用", "convert": "转换", "rewrite": "重写",
    "replace": "替代", "confirm": "待裁决",
}
_DISP_COLOR_KEY = {
    "reuse": "C_SUCCESS_TXT", "convert": "C_INFO_TXT", "rewrite": "C_WARNING_TXT",
    "replace": "C_WARNING_TXT", "confirm": "C_DANGER_TXT",
}


class _TreePage(QWidget):
    """通用树页：分组标题 + 可搜索条目 + 底部详情。"""

    def __init__(self, group_label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._group_label = group_label
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.search = QLineEdit()
        self.search.setPlaceholderText(f"搜索{group_label}…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        lay.addWidget(self.search)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["名称", "处置", "备注"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(False)
        self.tree.setWordWrap(True)
        self.tree.currentItemChanged.connect(self._show_detail)
        header = self.tree.header()
        header.setMinimumSectionSize(52)
        header.setSectionResizeMode(0, header.ResizeMode.Stretch)
        header.setSectionResizeMode(1, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, header.ResizeMode.Stretch)
        lay.addWidget(self.tree, stretch=1)

        self.detail = QLabel("选中条目后显示完整信息")
        self.detail.setObjectName("muted")
        self.detail.setMinimumHeight(60)
        lay.addWidget(self.detail)
        harden_window(self)

    def load_items(self, items: list[dict], columns: tuple[str, str, str]) -> None:
        """columns = (名称键, 处置键, 备注键)。"""
        self.tree.clear()
        groups: dict[str, list[dict]] = {}
        for it in items:
            key = str(it.get("type") or it.get("screen") or "其他")
            groups.setdefault(key, []).append(it)
        name_key, disp_key, note_key = columns
        for group, members in sorted(groups.items()):
            root = QTreeWidgetItem([f"{group}（{len(members)}）", "", ""])
            root.setFlags(root.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.tree.addTopLevelItem(root)
            for m in members:
                disp = str(m.get(disp_key, ""))
                child = QTreeWidgetItem([
                    str(m.get(name_key, "")),
                    _DISP_CN.get(disp, disp),
                    _short(str(m.get(note_key, "")), 40),
                ])
                child.setData(0, Qt.ItemDataRole.UserRole, m)
                for c in range(3):
                    text = plain_text(child.text(c))
                    if text:
                        child.setToolTip(c, text)
                if disp in _DISP_COLOR_KEY:
                    child.setForeground(1, _brush(disp))
                root.addChild(child)
            root.setExpanded(False)
        self.tree.expandToDepth(0)

    def _apply_filter(self, text: str) -> None:
        text = (text or "").strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            root = self.tree.topLevelItem(i)
            visible = 0
            for j in range(root.childCount()):
                child = root.child(j)
                hit = not text or text in child.text(0).lower() or text in child.text(2).lower()
                child.setHidden(not hit)
                visible += int(hit)
            root.setHidden(visible == 0)
            root.setText(0, root.text(0).split("（")[0] + f"（{visible}）")

    def _show_detail(self, current: QTreeWidgetItem | None, _prev=None) -> None:
        if current is None:
            self.detail.setText("选中条目后显示完整信息")
            return
        data = current.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            self.detail.setText("选中条目后显示完整信息")
            return
        lines = [f"<b>{data.get('id', '')}</b> {data.get('name') or data.get('topic') or ''}"]
        for k, v in data.items():
            if k in ("id", "name", "topic"):
                continue
            label = "处置" if k == "disposition" else k
            value = _DISP_CN.get(str(v), str(v)) if k == "disposition" else str(v)
            lines.append(f"<span style='color:{theme.C_FG_MUTED}'>{label}：</span>{_short(value, 160)}")
        self.detail.setText("<br>".join(lines))
        self.detail.setToolTip(plain_text(self.detail.text()))


def _brush(disp: str) -> QColor:
    return QColor(getattr(theme, _DISP_COLOR_KEY[disp]))


def _short(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


class InventoryPanel(QTabWidget):
    """左栏主体：文件 + 资源/模块/行为 四个 tab。"""

    refresh_requested = Signal()
    status_hint = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.files_page = FileBrowserPanel()
        self.files_page.status_hint.connect(self.status_hint)
        self.res_page = ResourceExplorerPanel()
        self.mod_page = _TreePage("模块")
        self.beh_page = _TreePage("行为")
        self.addTab(self.files_page, "文件")
        self.addTab(self.res_page, "资源")
        self.addTab(self.mod_page, "模块")
        self.addTab(self.beh_page, "行为")
        self.setMinimumWidth(320)
        harden_window(self)

    def set_zh(self, zh: bool) -> None:
        self.files_page.set_zh(zh)

    def refresh(self, session: ProjectSession) -> None:
        self.files_page.browse(session.project_dir)
        self.res_page.refresh(session)
        self.mod_page.load_items(session.modules, ("name", "disposition", "notes"))
        self.beh_page.load_items(session.behaviors, ("expected", "disposition", "notes"))
