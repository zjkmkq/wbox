"""wbox.gui.steps.decide_step —— ③ 判断：开放问题逐条人工裁决。

流程（写死）：
  左栏列出提案生成的开放问题（proposal.open_questions）→ 选中一条
  → 填结论（+可选理由）→ [记录决策] → 写 spec.decisions
  （id 自增、decided_by 恒为 human、decided_at 当前 UTC 时间）→ 落盘刷新。
  同一问题重复裁决时追加新决策（旧的不删，契约可回溯）。
"""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
)

from wbox.gui.session import ProjectSession
from wbox.gui.steps import StepPage, fill_text_table, register


@register
class DecideStep(StepPage):
    step_id = "decide"
    title = "③ 判断"
    subtitle = "逐条裁决提案里的开放问题：AI 只给选项和依据，决定权永远在人（decided_by=human）"

    # ------------------------------------------------------------ 构建

    def _build_body(self) -> None:
        split = QHBoxLayout()

        # 左：开放问题列表
        left = QVBoxLayout()
        left.addWidget(QLabel("提案开放问题（来自②画拼图）"))
        self.q_list = QListWidget()
        self.q_list.currentItemChanged.connect(self._on_question_selected)
        left.addWidget(self.q_list, stretch=2)
        split.addLayout(left, stretch=4)

        # 右：已做决策
        right = QVBoxLayout()
        right.addWidget(QLabel("已做决策（spec.decisions，可回溯）"))
        self.dec_table = QTableWidget()
        self.dec_table.setAlternatingRowColors(True)
        self.dec_table.setWordWrap(True)    # 问题/结论长文本换行（2026-10-25 遮挡修复）
        self.dec_table.verticalHeader().setVisible(False)
        self.dec_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.dec_table.setColumnCount(4)
        self.dec_table.setHorizontalHeaderLabels(["ID", "问题", "结论", "时间"])
        right.addWidget(self.dec_table, stretch=2)
        split.addLayout(right, stretch=6)
        self.body.addLayout(split, stretch=3)

        # 下：裁决表单
        form = QVBoxLayout()
        self.topic_edit = QLineEdit()
        self.topic_edit.setPlaceholderText("问题主题（选中左侧问题自动填入，可改）")
        form.addWidget(self.topic_edit)
        self.chosen_edit = QLineEdit()
        self.chosen_edit.setPlaceholderText("你的决定（必填）——例如：接受 toast 方案 / 继续寻找替代 API")
        form.addWidget(self.chosen_edit)
        self.reason_edit = QPlainTextEdit()
        self.reason_edit.setPlaceholderText("理由（可选）：依据、取舍、遗留风险")
        self.reason_edit.setMaximumHeight(90)
        form.addWidget(self.reason_edit)
        row = QHBoxLayout()
        self.btn_decide = QPushButton("记录决策")
        self.btn_decide.setObjectName("primary")
        self.btn_decide.clicked.connect(self._record)
        row.addWidget(self.btn_decide)
        self.dec_status = QLabel("")
        row.addWidget(self.dec_status)
        row.addStretch(1)
        form.addLayout(row)
        self.body.addLayout(form, stretch=2)

    # ------------------------------------------------------------ 动作

    def _on_question_selected(self, current: QListWidgetItem | None, _prev=None) -> None:
        if current is None:
            return
        q = current.data(Qt.ItemDataRole.UserRole)
        if not q:
            return
        self.topic_edit.setText(str(q.get("topic", "")))
        self.chosen_edit.clear()
        self.reason_edit.clear()
        self.chosen_edit.setFocus()

    def _record(self) -> None:
        topic = self.topic_edit.text().strip()
        chosen = self.chosen_edit.text().strip()
        if not topic or not chosen:
            self.dec_status.setText("问题主题与结论都不能为空")
            return
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        entry = {
            "id": self.session.next_id("decisions", "dec_"),
            "topic": topic,
            "chosen": chosen,
            "reason": self.reason_edit.toPlainText().strip(),
            "decided_by": "human",
            "decided_at": now,
        }
        self.session.spec.setdefault("decisions", []).append(entry)
        try:
            self.session.save("记录决策")
        except Exception as e:  # noqa: BLE001
            self.dec_status.setText(f"保存失败：{e}")
            return
        self.dec_status.setText(f"已记录 {entry['id']}")
        self.chosen_edit.clear()
        self.reason_edit.clear()

    # ------------------------------------------------------------ 刷新

    def refresh(self) -> None:
        # 问题列表（带已决标记）
        questions = self.session.spec.get("proposal", {}).get("open_questions", [])
        decided_topics = {str(d.get("topic", "")) for d in self.session.decisions}
        self.q_list.blockSignals(True)
        self.q_list.clear()
        for q in questions:
            topic = str(q.get("topic", ""))
            mark = " ✔已决" if topic in decided_topics else ""
            # QListWidgetItem 单行渲染：why 长文本进 tooltip，列表只留主题
            # （2026-10-25 修复：双行文本第二行被吞，用户看不到判定依据）
            item = QListWidgetItem(f"{topic}{mark}")
            why = str(q.get("why", ""))
            item.setToolTip(why or topic)
            item.setData(Qt.ItemDataRole.UserRole, q)
            self.q_list.addItem(item)
        self.q_list.blockSignals(False)

        # 决策表
        decisions = self.session.decisions
        rows = []
        for d in decisions:
            at = str(d.get("decided_at", ""))[:19].replace("T", " ")
            rows.append([d.get("id", ""), d.get("topic", ""), d.get("chosen", ""), at])
        # 问题/结论列长文本：换行 + 悬停全文（2026-10-25 遮挡修复）
        fill_text_table(self.dec_table, rows, ["ID", "问题", "结论", "时间"], wrap_cols={1, 2})

        pending = sum(1 for q in questions
                      if str(q.get("topic", "")) not in decided_topics)
        self.dec_status.setText(f"未决 {pending} 条 / 已决 {len(decisions)} 条")

    def on_enter(self) -> None:
        self.refresh()
