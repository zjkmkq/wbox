"""wbox.gui.pages.troubleshoot —— 排障台：跨工程的缝清单 + 失败案例 + 日志检索。

存在理由：缝（seams）散在各个工程的 spec.json 里，出问题时要挨个目录翻。
本页一次性汇总「最近工程」里所有的缝与构建日志，支持全文检索，
双击一条缝还能直接跳回它所属的工程继续处理。

数据仍经 wbox.spec 读取（唯一契约入口），绝不直接 json.load。
加载放 QThread 子类（读盘 + schema 校验不该卡 UI）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from wbox import config as app_config
from wbox import spec as spec_mod
from wbox.gui import theme
from wbox.gui.threads import track_thread
from wbox.gui.uikit import configure_table, harden_window, plain_text

_SEAM_STATUS_CN = {
    "open": "待补", "fixed": "已修待验", "verified": "已验证", "wontfix": "不补",
}
_SEAM_COLOR = {
    "open": "C_DANGER_TXT", "fixed": "C_WARNING_TXT",
    "verified": "C_SUCCESS_TXT", "wontfix": "C_FG_MUTED",
}
_SEAM_HEADERS = ["工程", "类型", "对不上的点", "影响", "状态", "修复方案"]
_SEAM_STRETCH = {2, 3, 5}
_LOG_HEADERS = ["工程", "时间", "动作", "摘要"]
_LOG_STRETCH = {3}
_ACTION_CN = {
    "extracted": "拆解", "draft_generated": "草案生成", "compile_verified": "编译验证",
    "human_edited": "人工修改", "confirmed": "已确认", "rolled_back": "已回滚",
    "runtime_fixed": "运行修复",
}


@dataclass
class ProjectDump:
    """一个工程加载后的排障数据（加载失败也留一条记录，不静默跳过）。"""

    name: str
    path: str
    seams: list[dict]
    logs: list[dict]
    error: str = ""


class _ScanThread(QThread):
    """后台读取最近工程的 spec（含 schema 校验）。"""

    done = Signal(list)

    def __init__(self, entries: list[dict], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._entries = entries

    def run(self) -> None:
        dumps: list[ProjectDump] = []
        for e in self._entries:
            path = Path(str(e.get("path") or ""))
            name = str(e.get("name") or path.name)
            if not (path / "spec.json").is_file():
                dumps.append(ProjectDump(name, str(path), [], [], "目录下没有 spec.json"))
                continue
            try:
                spec = spec_mod.load(path / "spec.json")
            except (spec_mod.SpecError, OSError, ValueError) as exc:
                dumps.append(ProjectDump(name, str(path), [], [], str(exc)))
                continue
            dumps.append(ProjectDump(
                name=str(spec.get("project", {}).get("name") or name),
                path=str(path),
                seams=list(spec.get("seams") or []),
                logs=list(spec.get("build_log") or []),
            ))
        self.done.emit(dumps)


class TroubleshootPage(QWidget):
    """排障台页面。"""

    back = Signal()
    open_project = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dumps: list[ProjectDump] = []
        self._thread: _ScanThread | None = None
        self._loaded = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)

        head = QHBoxLayout()
        btn_back = QPushButton("← 首页")
        btn_back.clicked.connect(self.back.emit)
        head.addWidget(btn_back)
        title = QLabel("排障台")
        title.setObjectName("h1")
        head.addWidget(title)
        head.addStretch(1)
        self.btn_reload = QPushButton("重新加载")
        self.btn_reload.clicked.connect(self.reload)
        head.addWidget(self.btn_reload)
        lay.addLayout(head)

        self.search = QLineEdit()
        self.search.setPlaceholderText("全文检索：缝的来源 / 影响 / 修复方案 / 日志摘要…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self._refill())
        lay.addWidget(self.search)

        self.status_label = QLabel("")
        self.status_label.setObjectName("muted")
        lay.addWidget(self.status_label)

        self.tabs = QTabWidget()
        self.table_seams = self._make_table(_SEAM_HEADERS, _SEAM_STRETCH)
        self.table_seams.doubleClicked.connect(self._open_current_project)
        self.table_logs = self._make_table(_LOG_HEADERS, _LOG_STRETCH)
        self.table_logs.doubleClicked.connect(self._open_current_project)
        self.tabs.addTab(self.table_seams, "缝清单")
        self.tabs.addTab(self.table_logs, "构建日志")
        lay.addWidget(self.tabs, stretch=1)

        hint = QLabel("双击任意一行可直接打开该行所属的工程。")
        hint.setObjectName("muted")
        lay.addWidget(hint)

        harden_window(self)
        # 构造不读盘：等页面真正被切到再加载（离屏冒烟不能留活线程）
        self.status_label.setText("点击「重新加载」汇总最近工程的缝与日志")

    # ------------------------------------------------------------ 表格

    def _make_table(self, headers: list[str], stretch: set[int]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        configure_table(table, headers, stretch_cols=stretch)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        return table

    @staticmethod
    def _put(table: QTableWidget, row: int, col: int, text: str,
             project_path: str, color_key: str = "") -> None:
        item = QTableWidgetItem(text)
        item.setToolTip(plain_text(text))
        item.setData(Qt.ItemDataRole.UserRole, project_path)
        if color_key:
            item.setForeground(QColor(getattr(theme, color_key)))
        table.setItem(row, col, item)

    # ------------------------------------------------------------ 加载

    def reload_if_needed(self) -> None:
        """页面首次被切到时才加载（避免一进应用就在后台读全部工程）。"""
        if not self._loaded:
            self.reload()

    def reload(self) -> None:
        cfg = app_config.load()
        entries = list(cfg.get("recent_projects", []))
        if not entries:
            self._dumps = []
            self.status_label.setText("还没有最近工程：先去「五步专家模式」打开或新建一个工程。")
            self._refill()
            return
        self.status_label.setText(f"正在读取 {len(entries)} 个最近工程…")
        if self._thread is not None and self._thread.isRunning():
            return
        th = track_thread(_ScanThread(entries))
        th.done.connect(self._on_loaded)
        self._thread = th
        th.start()

    def _on_loaded(self, dumps: list) -> None:
        self._loaded = True
        self._dumps = list(dumps)
        errors = [d for d in self._dumps if d.error]
        total_seams = sum(len(d.seams) for d in self._dumps)
        open_seams = sum(1 for d in self._dumps for s in d.seams
                         if str(s.get("status", "open")) == "open")
        text = f"已加载 {len(self._dumps)} 个工程，共 {total_seams} 条缝（其中 {open_seams} 条待补）"
        if errors:
            text += f"；{len(errors)} 个工程读取失败：" + "、".join(d.name for d in errors[:3])
        self.status_label.setText(text)
        self.status_label.setToolTip(plain_text(text))
        self._refill()

    # ------------------------------------------------------------ 填充

    def _refill(self) -> None:
        keyword = self.search.text().strip().lower()
        seam_rows: list[tuple[ProjectDump, dict]] = []
        log_rows: list[tuple[ProjectDump, dict]] = []
        for d in self._dumps:
            for s in d.seams:
                hay = " ".join(str(s.get(k, "")) for k in
                               ("id", "type", "source", "impact", "fix", "status")).lower()
                if keyword and keyword not in hay:
                    continue
                seam_rows.append((d, s))
            for entry in d.logs:
                hay = " ".join(str(entry.get(k, "")) for k in
                               ("id", "action", "summary")).lower()
                if keyword and keyword not in hay:
                    continue
                log_rows.append((d, entry))

        table = self.table_seams
        table.setRowCount(len(seam_rows))
        for r, (d, s) in enumerate(seam_rows):
            status = str(s.get("status", "open"))
            self._put(table, r, 0, d.name, d.path)
            self._put(table, r, 1, str(s.get("type", "")), d.path)
            self._put(table, r, 2, str(s.get("source", "")), d.path)
            self._put(table, r, 3, str(s.get("impact", "")), d.path)
            self._put(table, r, 4, _SEAM_STATUS_CN.get(status, status), d.path,
                      _SEAM_COLOR.get(status, "C_FG"))
            self._put(table, r, 5, str(s.get("fix", "") or "—"), d.path)
        table.resizeRowsToContents()

        logs = self.table_logs
        logs.setRowCount(len(log_rows))
        for r, (d, entry) in enumerate(reversed(log_rows)):
            action = str(entry.get("action", ""))
            self._put(logs, r, 0, d.name, d.path)
            self._put(logs, r, 1, str(entry.get("at", ""))[:16].replace("T", " "), d.path)
            self._put(logs, r, 2, _ACTION_CN.get(action, action), d.path)
            self._put(logs, r, 3, str(entry.get("summary", "")), d.path)
        logs.resizeRowsToContents()

    # ------------------------------------------------------------ 跳转

    def _open_current_project(self) -> None:
        table = self.tabs.currentWidget()
        if not isinstance(table, QTableWidget):
            return
        row = table.currentRow()
        if row < 0:
            return
        item = table.item(row, 0)
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.open_project.emit(str(path))

    def wait_thread(self, msec: int = 5000) -> None:
        th = self._thread
        if th is not None and th.isRunning():
            th.wait(msec)
