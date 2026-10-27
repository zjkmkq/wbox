"""wbox.gui.panels.records —— 右栏：校验与测试记录。

三个 tab：编译记录（build_log 时间线）/ 补缝（seams 状态板）/ 决策（decisions）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from wbox.gui.session import ProjectSession
from wbox.gui import theme

_SEAM_STATUS = {
    "open": "待补", "fixed": "已修待验", "verified": "已验证", "wontfix": "不补",
}
_SEAM_COLOR_KEY = {
    "open": "C_DANGER_TXT", "fixed": "C_WARNING_TXT",
    "verified": "C_SUCCESS_TXT", "wontfix": "C_FG_MUTED",
}

_ACTION_CN = {
    "extracted": "拆解",
    "draft_generated": "草案生成",
    "compile_verified": "编译验证",
    "human_edited": "人工修改",
    "confirmed": "已确认",
    "rolled_back": "已回滚",
    "runtime_fixed": "运行修复",
}


class _BuildLogPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setAlternatingRowColors(True)
        lay.addWidget(self.list)

    def refresh(self, session: ProjectSession) -> None:
        self.list.clear()
        for entry in reversed(session.build_log):
            action = _ACTION_CN.get(str(entry.get("action", "")), str(entry.get("action", "")))
            at = str(entry.get("at", ""))[:16].replace("T", " ")
            item = QListWidgetItem(f"[{at}] {action}  {entry.get('id', '')}\n{_short(entry.get('summary', ''), 120)}")
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.list.addItem(item)


class _SeamsPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["ID", "类型", "对不上的点", "状态"])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, hh.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, hh.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, hh.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, hh.ResizeMode.ResizeToContents)
        lay.addWidget(self.table)

    def refresh(self, session: ProjectSession) -> None:
        rows = session.seams
        self.table.setRowCount(len(rows))
        for r, s in enumerate(rows):
            status = str(s.get("status", "open"))
            label = _SEAM_STATUS.get(status, status)
            color = getattr(theme, _SEAM_COLOR_KEY.get(status, "C_FG"))
            vals = [str(s.get("id", "")), str(s.get("type", "")), _short(str(s.get("source", "")), 60), label]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c == 3:
                    item.setForeground(QColor(color))
                self.table.setItem(r, c, item)


class _DecisionsPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["ID", "议题", "结论"])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, hh.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, hh.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, hh.ResizeMode.Stretch)
        lay.addWidget(self.table)

    def refresh(self, session: ProjectSession) -> None:
        rows = session.decisions
        self.table.setRowCount(len(rows))
        for r, d in enumerate(rows):
            vals = [str(d.get("id", "")), str(d.get("topic", "")), str(d.get("chosen", ""))]
            for c, v in enumerate(vals):
                self.table.setItem(r, c, QTableWidgetItem(v))


def _short(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


class RecordsPanel(QTabWidget):
    """右栏主体。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.build_page = _BuildLogPage()
        self.seams_page = _SeamsPage()
        self.dec_page = _DecisionsPage()
        self.addTab(self.build_page, "编译记录")
        self.addTab(self.seams_page, "补缝")
        self.addTab(self.dec_page, "决策")

    def refresh(self, session: ProjectSession) -> None:
        self.build_page.refresh(session)
        self.seams_page.refresh(session)
        self.dec_page.refresh(session)
