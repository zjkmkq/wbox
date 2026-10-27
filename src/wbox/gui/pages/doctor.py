"""wbox.gui.pages.doctor —— 形态诊断仪：只丢 APK，先回答"能不能迁、几步、有哪些坑"。

存在理由：用户常常只有一个 APK，想知道"这玩意儿到底是什么形态"再决定动手。
本页把 wbox.shape 的模板匹配结果可视化：命中形态 + 证据 + 迁移步骤 + 坑 + 验收清单。

铁律：扫描（读 zip/目录 + 正则）放 QThread 子类的 run() 里，UI 不卡；
线程不用 moveToThread+quit 那套（quit 会丢，进程退不出）。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from wbox import shape as shape_mod
from wbox.gui import theme
from wbox.gui.threads import track_thread
from wbox.gui.uikit import harden_window, plain_text, wrap_label

_RESULT_HEADERS = ["现象", "原因", "解法"]


class _DiagnoseThread(QThread):
    """后台扫描 APK/目录：只做只读扫描，不写任何文件。"""

    done = Signal(list, str)
    failed = Signal(str)

    def __init__(self, target: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._target = target

    def run(self) -> None:
        try:
            matches = shape_mod.detect_shape(self._target)
            report = shape_mod.report_text(self._target, matches)
            self.done.emit(matches, report)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class DoctorPage(QWidget):
    """形态诊断仪页面。"""

    back = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._thread: _DiagnoseThread | None = None
        self._matches: list[shape_mod.Match] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)

        head = QHBoxLayout()
        btn_back = QPushButton("← 首页")
        btn_back.clicked.connect(self.back.emit)
        head.addWidget(btn_back)
        title = QLabel("形态诊断仪")
        title.setObjectName("h1")
        head.addWidget(title)
        head.addStretch(1)
        lay.addLayout(head)

        lay.addWidget(wrap_label(
            "选一个 APK（或已解包的目录），工作台会比对形态模板库，回答：这是什么形态、"
            "能不能迁、大概几步、有哪些已知的坑。只读扫描，不改你任何文件。",
            object_name="muted"))

        pick = QHBoxLayout()
        self.btn_pick = QPushButton("选择 APK / 解包目录…")
        self.btn_pick.setObjectName("primary")
        self.btn_pick.clicked.connect(self._pick)
        self.path_label = QLabel("（未选择）")
        self.path_label.setObjectName("muted")
        pick.addWidget(self.btn_pick)
        pick.addWidget(self.path_label, stretch=1)
        lay.addLayout(pick)

        self.verdict = QLabel("")
        self.verdict.setObjectName("h2")
        lay.addWidget(self.verdict)

        self.evidence = QTreeWidget()
        self.evidence.setHeaderLabels(["判定证据"])
        self.evidence.setRootIsDecorated(False)
        self.evidence.setWordWrap(True)
        self.evidence.setUniformRowHeights(False)
        self.evidence.setMaximumHeight(130)
        lay.addWidget(self.evidence)

        self.pitfalls = QTreeWidget()
        self.pitfalls.setHeaderLabels(_RESULT_HEADERS)
        self.pitfalls.setWordWrap(True)
        self.pitfalls.setUniformRowHeights(False)
        self.pitfalls.setAlternatingRowColors(True)
        header = self.pitfalls.header()
        header.setMinimumSectionSize(60)
        for c in range(3):
            header.setSectionResizeMode(c, header.ResizeMode.Stretch)
        lay.addWidget(self.pitfalls, stretch=1)

        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.report.setPlaceholderText("诊断报告将显示在这里（可全选复制）")
        lay.addWidget(self.report, stretch=1)

        harden_window(self)

    # ------------------------------------------------------------ 交互

    def _pick(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 APK 或 Zip", "", "安装包 (*.apk *.zip);;所有文件 (*.*)")
        if not path:
            d = QFileDialog.getExistingDirectory(self, "或选择已解包的目录")
            if not d:
                return
            path = d
        self.diagnose(path)

    def diagnose(self, path: str) -> None:
        self.path_label.setText(path)
        self.path_label.setToolTip(path)
        self.verdict.setText("正在扫描…（大包可能要十几秒）")
        self.verdict.setStyleSheet("")
        self.report.setPlainText("")
        self.evidence.clear()
        self.pitfalls.clear()
        if self._thread is not None and self._thread.isRunning():
            return
        th = track_thread(_DiagnoseThread(path))
        th.done.connect(self._on_done)
        th.failed.connect(self._on_failed)
        self._thread = th
        th.start()

    def _on_failed(self, message: str) -> None:
        self.verdict.setText("诊断失败")
        self.verdict.setStyleSheet(f"color: {theme.C_DANGER_TXT};")
        self.report.setPlainText(f"扫描出错：{message}")

    def _on_done(self, matches: list, report: str) -> None:
        self._matches = list(matches)
        self.report.setPlainText(report)
        if not matches:
            self.verdict.setText("未命中已知形态模板")
            self.verdict.setStyleSheet(f"color: {theme.C_WARNING_TXT};")
            self.verdict.setToolTip("模板库尚未覆盖该类型；可先用「① 拆」解包人工判读")
            return
        top = matches[0]
        effort = str(top.shape.get("effort") or "—")
        self.verdict.setText(
            f"判定：{top.name}（置信度 {top.confidence}）　预计工作量：{effort}")
        self.verdict.setStyleSheet(f"color: {theme.C_SUCCESS_TXT};")
        self.verdict.setToolTip(plain_text(str(top.shape.get("summary") or top.name)))

        self.evidence.clear()
        for e in top.evidence:
            item = QTreeWidgetItem([str(e)])
            item.setToolTip(0, str(e))
            self.evidence.addTopLevelItem(item)
        self.evidence.resizeColumnToContents(0)

        self.pitfalls.clear()
        for p in (top.shape.get("migrate") or {}).get("pitfalls", []) or []:
            vals = [str(p.get("symptom", "")), str(p.get("cause", "")), str(p.get("fix", ""))]
            item = QTreeWidgetItem(vals)
            for c, v in enumerate(vals):
                item.setToolTip(c, plain_text(v))
            self.pitfalls.addTopLevelItem(item)
        self.pitfalls.resizeColumnToContents(0)

    def wait_thread(self, msec: int = 5000) -> None:
        th = self._thread
        if th is not None and th.isRunning():
            th.wait(msec)

    @property
    def current_path(self) -> str:
        return self.path_label.text()
