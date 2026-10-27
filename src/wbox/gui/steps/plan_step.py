"""wbox.gui.steps.plan_step —— ② 画拼图：提案生成 + 映射编辑器。

流程（写死）：
  [生成提案] → wbox.plan.generate_proposal（纯本地启发式，毫秒级）
  → 写回 spec["proposal"] 并落盘 → 三张表（资源搬迁/逻辑类/UI 单元）+
  待裁决列表，全部可编辑（action 下拉 / target 手改 / reason 只读）。
  编辑即存（原子写），主窗左右栏随 session.changed 联动。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
)

from wbox.gui.session import ProjectSession
from wbox.gui.steps import StepPage, register
from wbox.gui import theme
from wbox.plan import generate_proposal

_ACTION_CN = {"migrate": "迁移", "convert": "转换", "drop": "弃用", "keep": "保留"}
_PATTERN_CN = {
    "page": "页面", "component": "组件", "dialog": "对话框",
    "state-store": "中央状态", "pure-logic": "纯逻辑", "persistence": "持久化", "service": "服务",
}


class _ProposalTable(QTableWidget):
    """提案表基类：编辑即写回 session.spec 并落盘。"""

    def __init__(self, session: ProjectSession, parent=None) -> None:
        super().__init__(parent)
        self.session = session
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.verticalHeader().setVisible(False)
        self.itemChanged.connect(self._on_changed)

    # ------------------------------------------------------------ 子类实现

    def _rows(self) -> list[dict]:
        raise NotImplementedError

    def _columns(self) -> list[str]:
        raise NotImplementedError

    def _cell(self, row: dict, col: int) -> str:
        raise NotImplementedError

    def _apply_edit(self, row: dict, col: int, value: str) -> None:
        raise NotImplementedError

    def _editable_cols(self) -> set[int]:
        return set()

    # ------------------------------------------------------------ 公共

    def refresh(self) -> None:
        self.blockSignals(True)
        self.clear()
        rows = self._rows()
        self.setRowCount(len(rows))
        self.setColumnCount(len(self._columns()))
        self.setHorizontalHeaderLabels(self._columns())
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(0, hh.ResizeMode.ResizeToContents)
        for c in range(1, len(self._columns())):
            hh.setSectionResizeMode(c, hh.ResizeMode.Stretch)
        for r, row in enumerate(rows):
            for c in range(len(self._columns())):
                item = QTableWidgetItem(self._cell(row, c))
                if c not in self._editable_cols():
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setData(Qt.ItemDataRole.UserRole, row)
                self.setItem(r, c, item)
        self.blockSignals(False)

    def _on_changed(self, item: QTableWidgetItem) -> None:
        row = item.data(Qt.ItemDataRole.UserRole)
        if not row:
            return
        self._apply_edit(row, item.column(), item.text().strip())
        try:
            self.session.save("提案编辑")
        except Exception as e:  # noqa: BLE001
            self._show_error(str(e))

    def _show_error(self, msg: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(self, "保存失败", msg)


class _ResourceTable(_ProposalTable):
    def _rows(self) -> list[dict]:
        return self.session.spec.get("proposal", {}).get("resource_moves", [])

    def _columns(self) -> list[str]:
        return ["资源", "动作", "目标路径", "理由"]

    def _cell(self, row: dict, col: int) -> str:
        return [row.get("name", ""), _ACTION_CN.get(row.get("action", ""), row.get("action", "")),
                row.get("target", ""), row.get("reason", "")][col]

    def _editable_cols(self) -> set[int]:
        return {1, 2}

    def _apply_edit(self, row: dict, col: int, value: str) -> None:
        if col == 1:
            inv = {v: k for k, v in _ACTION_CN.items()}
            row["action"] = inv.get(value, row.get("action"))
        elif col == 2:
            row["target"] = value


class _LogicTable(_ProposalTable):
    def _rows(self) -> list[dict]:
        return self.session.spec.get("proposal", {}).get("logic_classes", [])

    def _columns(self) -> list[str]:
        return ["模块", "模式", "目标文件", "理由"]

    def _cell(self, row: dict, col: int) -> str:
        return [row.get("name", ""), _PATTERN_CN.get(row.get("pattern", ""), row.get("pattern", "")),
                row.get("target", ""), row.get("reason", "")][col]

    def _editable_cols(self) -> set[int]:
        return {1, 2}

    def _apply_edit(self, row: dict, col: int, value: str) -> None:
        if col == 1:
            inv = {v: k for k, v in _PATTERN_CN.items()}
            row["pattern"] = inv.get(value, row.get("pattern"))
        elif col == 2:
            row["target"] = value


class _UiTable(_ProposalTable):
    def _rows(self) -> list[dict]:
        return self.session.spec.get("proposal", {}).get("ui_units", [])

    def _columns(self) -> list[str]:
        return ["屏", "类型", "目标文件", "归并行为数", "理由"]

    def _cell(self, row: dict, col: int) -> str:
        return [row.get("screen", ""), {"page": "页面", "dialog": "对话框", "component": "组件"}.get(row.get("kind", ""), row.get("kind", "")),
                row.get("target", ""), str(len(row.get("beh_ids", []))), row.get("reason", "")][col]

    def _editable_cols(self) -> set[int]:
        return {1, 2}

    def _apply_edit(self, row: dict, col: int, value: str) -> None:
        if col == 1:
            inv = {"页面": "page", "对话框": "dialog", "组件": "component"}
            row["kind"] = inv.get(value, row.get("kind"))
        elif col == 2:
            row["target"] = value


@register
class PlanStep(StepPage):
    step_id = "plan"
    title = "② 画拼图"
    subtitle = "把三段清单映射成鸿蒙结构提案：资源→rawfile 搬迁、逻辑→logic 类、行为→页面/组件"

    def _build_body(self) -> None:
        bar = QHBoxLayout()
        self.btn_gen = QPushButton("生成 / 重新生成提案")
        self.btn_gen.setObjectName("primary")
        self.btn_gen.clicked.connect(self._generate)
        bar.addWidget(self.btn_gen)
        self.filter_box = QComboBox()
        self.filter_box.addItems(["全部资源", "仅迁移", "仅弃用"])
        self.filter_box.currentTextChanged.connect(self._apply_filter)
        bar.addWidget(self.filter_box)
        bar.addStretch(1)
        self.summary = QLabel("")
        bar.addWidget(self.summary)
        self.body.addLayout(bar)

        self.tabs = QTabWidget()
        self.res_table = _ResourceTable(self.session)
        self.logic_table = _LogicTable(self.session)
        self.ui_table = _UiTable(self.session)
        self.tabs.addTab(self.res_table, "资源搬迁")
        self.tabs.addTab(self.logic_table, "逻辑类划分")
        self.tabs.addTab(self.ui_table, "UI 单元")
        self.body.addWidget(self.tabs, stretch=1)

        # 待裁决
        self.q_list = QVBoxLayout()
        q_wrap = QVBoxLayout()
        self._q_container = QVBoxLayout()
        q_wrap.addLayout(self._q_container)
        q_wrap.addStretch(1)
        self.body.addLayout(q_wrap, stretch=0)

    # ------------------------------------------------------------ 动作

    def _generate(self) -> None:
        proposal = generate_proposal(self.session.spec)
        self.session.spec["proposal"] = proposal
        self.session.save("生成提案")
        self.refresh()

    def _apply_filter(self, _text: str) -> None:
        mode = self.filter_box.currentText()
        for r in range(self.res_table.rowCount()):
            item = self.res_table.item(r, 1)
            if item is None:
                continue
            if mode == "全部资源":
                self.res_table.setRowHidden(r, False)
            else:
                want = "迁移" if mode == "仅迁移" else "弃用"
                self.res_table.setRowHidden(r, item.text() != want)

    def refresh(self) -> None:
        has = "proposal" in self.session.spec
        self.res_table.refresh()
        self.logic_table.refresh()
        self.ui_table.refresh()
        if has:
            p = self.session.spec["proposal"]
            mig = sum(1 for m in p.get("resource_moves", []) if m.get("action") == "migrate")
            drop = sum(1 for m in p.get("resource_moves", []) if m.get("action") == "drop")
            self.summary.setText(
                f"迁移 {mig} / 弃 {drop} · 逻辑类 {len(p.get('logic_classes', []))} · "
                f"UI 单元 {len(p.get('ui_units', []))} · 待裁决 {len(p.get('open_questions', []))}")
        else:
            self.summary.setText("尚未生成提案")
        self._refresh_questions()

    def _refresh_questions(self) -> None:
        while self._q_container.count():
            child = self._q_container.takeAt(0)
            w = child.widget()
            if w is not None:
                w.deleteLater()
        questions = self.session.spec.get("proposal", {}).get("open_questions", [])
        head = QLabel(f"待人工裁决（{len(questions)}）——带着这些问题进入「③ 判断」")
        head.setObjectName("h2")
        self._q_container.addWidget(head)
        for q in questions:
            label = QLabel(f"• {q.get('topic', '')}\n  <span style='color:{theme.C_FG_MUTED}'>{q.get('why', '')}</span>")
            label.setWordWrap(True)
            self._q_container.addWidget(label)

    def on_enter(self) -> None:
        self.refresh()
