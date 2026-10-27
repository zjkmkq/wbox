"""wbox.gui.steps —— 六步流程页面基座与注册表。

六步（写死顺序）：拆 → 画拼图 → 判断 → 填上 → 装配 → 补缝。
每个 StepPage 子类实现 refresh()/on_enter()；主窗负责切换与保存。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QTableWidgetItem, QVBoxLayout, QWidget

from wbox.gui.session import ProjectSession


def fill_text_table(table, rows: list[list[str]], headers: list[str],
                    wrap_cols: set[int] | None = None) -> None:
    """填表格并保证长文字不被"隐形截断"。

    用户实测（2026-10-25）：表格列宽固定/均分时，超宽文字被 Qt 单行
    elide 成 "…"，既看不清也没有提示，等于信息丢失。统一策略：
      1. wrap_cols 列开 wordWrap（行高自适应，完整可见）
      2. 其余列 ResizeToContents（能窄则窄，把空间让给内容列）
      3. 每个单元格 tooltip = 全文（窄列悬停可见）
      4. fill 期间 blockSignals，避免 itemChanged 误触发保存
    """
    wrap_cols = wrap_cols or set()
    table.blockSignals(True)
    try:
        # 单元格换行是 QTableView 级属性（QTableWidgetItem 无 setWordWrap）
        table.setWordWrap(True)
        table.clear()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(len(rows))
        hh = table.horizontalHeader()
        for c in range(len(headers)):
            if c in wrap_cols:
                hh.setSectionResizeMode(c, hh.ResizeMode.Stretch)
            else:
                hh.setSectionResizeMode(c, hh.ResizeMode.ResizeToContents)
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                item = QTableWidgetItem(text)
                item.setToolTip(text)          # 窄列悬停看全文
                table.setItem(r, c, item)
        table.resizeRowsToContents()
    finally:
        table.blockSignals(False)


class StepPage(QWidget):
    """五步页面基类。子类按 step_id 注册进 STEPS。"""

    step_id: str = ""
    title: str = ""
    subtitle: str = ""
    # 子类可发信号请求主窗切步/刷新左右栏
    navigate = Signal(str)

    def __init__(self, session: ProjectSession, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)
        head = QLabel(f"{self.title} —— {self.subtitle}")
        head.setObjectName("h2")
        head.setWordWrap(True)
        lay.addWidget(head)
        self.body = QVBoxLayout()
        lay.addLayout(self.body, stretch=1)
        self._build_body()
        session.changed.connect(lambda _note: self.refresh())

    def _build_body(self) -> None:
        """子类填充 self.body。"""
        placeholder = QLabel("（骨架占位：该步内容在后续迭代实现）")
        placeholder.setObjectName("muted")
        self.body.addWidget(placeholder)

    def refresh(self) -> None:
        """spec 变化后刷新本页。"""

    def on_enter(self) -> None:
        """切换到此步时调用（懒加载/聚焦）。"""


STEPS: list[type[StepPage]] = []


def register(cls: type[StepPage]) -> type[StepPage]:
    STEPS.append(cls)
    return cls


def step_order() -> list[str]:
    return [c.step_id for c in STEPS]
