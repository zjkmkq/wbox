"""wbox.gui.steps.seal_step —— ⑥ 补缝：编译验证 + 缝状态板。

流程（写死）：
  鸿蒙工程目录（默认由 ⑤ 装配 产出，记忆本工程目录）→ [开始编译]
  → _BuildWorker 后台线程流式跑 hvigor.run_build（node+hvigorw+SDK 由 deps 解析）
  → 成功：spec.build_log 记 compile_verified（含 HAP 路径与字节数）
  → 失败：spec.build_log 记 runtime_fixed（含错误摘要，供下一轮修）
  缝状态板：spec.seams 全量呈现，状态/验证结果列可编辑（编辑即存）。
  行为缝（behavior）必须真机对比后才允许标 verified——界面常驻提示。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from wbox import config as app_config
from wbox import deps as dep_mod
from wbox import hvigor
from wbox.gui.session import ProjectSession
from wbox.gui.steps import StepPage, register
from wbox.gui import theme

_STATUS_CN = {"open": "待补", "fixed": "已修待验", "verified": "已验证", "wontfix": "不处理"}
# 状态 -> 主题感知的语义色键（运行时取 theme.C_*，切主题自动跟随）
_STATUS_COLOR_KEY = {
    "open": "C_DANGER_TXT", "fixed": "C_INFO_TXT",
    "verified": "C_SUCCESS_TXT", "wontfix": "C_WARNING_TXT",
}


def _status_color_hex(status: str) -> str:
    return getattr(theme, _STATUS_COLOR_KEY.get(status, "C_FG"))


_TYPE_CN = {
    "logic": "逻辑缝", "resource": "资源缝", "behavior": "行为缝",
    "ecosystem": "生态缝", "data": "数据缝",
}


class _BuildWorker(QThread):
    """后台跑 hvigor.run_build；日志逐行抛出，结束抛结果。"""

    log_line = Signal(str)
    finished = Signal(bool, str, str)   # ok, summary_or_error, hap_path

    def __init__(self, project_dir: str) -> None:
        super().__init__()
        self.project_dir = project_dir

    def run(self) -> None:
        r = hvigor.run_build(self.project_dir, on_line=self.log_line.emit)
        self.finished.emit(r.ok, r.summary if r.ok else r.error, r.hap_path)


@register
class SealStep(StepPage):
    step_id = "seal"
    title = "⑥ 补缝"
    subtitle = "命令行编译验证鸿蒙草案工程；编译通过只是起点，行为缝必须真机对比后才算补上"

    # ------------------------------------------------------------ 构建

    def _build_body(self) -> None:
        # 工具条：工程目录 + 编译按钮 + 状态
        bar = QHBoxLayout()
        bar.addWidget(QLabel("鸿蒙工程目录："))
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText("含 build-profile.json5 的鸿蒙工程根目录")
        self.dir_edit.textChanged.connect(self._update_dir_status)
        bar.addWidget(self.dir_edit, stretch=1)
        self.btn_browse = QPushButton("浏览…")
        self.btn_browse.clicked.connect(self._browse)
        bar.addWidget(self.btn_browse)
        self.btn_build = QPushButton("开始编译")
        self.btn_build.setObjectName("primary")
        self.btn_build.clicked.connect(self._start_build)
        bar.addWidget(self.btn_build)
        self.status = QLabel("")
        bar.addWidget(self.status)
        self.body.addLayout(bar)

        # 依赖体检提示行
        self.dep_label = QLabel("")
        self.dep_label.setObjectName("muted")
        self.body.addWidget(self.dep_label)

        # 编译日志
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(4000)
        self.console.setStyleSheet("font-family: Consolas, 'Courier New', monospace;")
        self.body.addWidget(self.console, stretch=2)

        # 缝状态板 / 编译记录
        self.tabs = QTabWidget()

        # 缝状态板（带工具条：新增/删除）
        seam_tab = QWidget()
        seam_lay = QVBoxLayout(seam_tab)
        seam_lay.setContentsMargins(0, 0, 0, 0)
        seam_bar = QHBoxLayout()
        self.btn_add_seam = QPushButton("+ 新增缝")
        self.btn_add_seam.setObjectName("primary")
        self.btn_add_seam.clicked.connect(self._add_seam)
        seam_bar.addWidget(self.btn_add_seam)
        self.btn_del_seam = QPushButton("- 删除所选")
        self.btn_del_seam.clicked.connect(self._del_seam)
        seam_bar.addWidget(self.btn_del_seam)
        self.seam_bar_status = QLabel("")
        self.seam_bar_status.setObjectName("muted")
        seam_bar.addWidget(self.seam_bar_status, stretch=1)
        seam_lay.addLayout(seam_bar)

        self.seam_table = QTableWidget()
        self.seam_table.setAlternatingRowColors(True)
        self.seam_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.seam_table.setWordWrap(True)   # 长文本单元格换行（2026-10-25 遮挡修复）
        self.seam_table.verticalHeader().setVisible(False)
        self.seam_table.itemChanged.connect(self._on_seam_changed)
        seam_lay.addWidget(self.seam_table, stretch=1)
        self.tabs.addTab(seam_tab, "缝状态板")

        self.log_table = QTableWidget()
        self.log_table.setAlternatingRowColors(True)
        self.log_table.setWordWrap(True)    # 摘要长文本换行（2026-10-25 遮挡修复）
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabs.addTab(self.log_table, "编译记录")
        self.body.addWidget(self.tabs, stretch=3)

        hint = QLabel("提示：编译 unsigned HAP 只证明「能构建」；行为缝标「已验证」前必须真机对比原版。")
        hint.setObjectName("muted")
        self.body.addWidget(hint)

        self._worker: _BuildWorker | None = None

    # ------------------------------------------------------------ 动作

    def _browse(self) -> None:
        start = self.dir_edit.text() or str(self.session.draft_dir)
        d = QFileDialog.getExistingDirectory(self, "选择鸿蒙工程目录", start)
        if not d:
            return
        self.dir_edit.setText(d)
        cfg = app_config.load()
        cfg.setdefault("tools", {})["last_harmony_dir"] = d
        app_config.save(cfg)

    def _start_build(self) -> None:
        project = self.dir_edit.text().strip()
        if not project:
            self.status.setText("请先选择鸿蒙工程目录")
            return
        p = Path(project)
        if not (p / "build-profile.json5").is_file():
            self.status.setText(f"不是鸿蒙工程目录（缺 build-profile.json5）：{project}")
            return
        tc = dep_mod.resolve_toolchain()
        if tc is None:
            self.status.setText("未找到命令行工具链（hvigorw+SDK）：请到首页依赖体检安装")
            return

        self.btn_build.setEnabled(False)
        self.status.setText("编译中…")
        self.console.clear()
        self._worker = _BuildWorker(project)
        self._worker.log_line.connect(self._append_log)
        self._worker.finished.connect(self._on_build_done)
        self._worker.start()

    def _append_log(self, line: str) -> None:
        self.console.appendPlainText(line)

    def _on_build_done(self, ok: bool, message: str, hap: str) -> None:
        self.btn_build.setEnabled(True)
        text = ("编译通过" if ok else "编译失败") + f"：{message[:80]}"
        self.status.setText(text)
        # 状态条空间有限，80 字外全文进 tooltip（2026-10-25 遮挡修复）
        self.status.setToolTip(("编译通过" if ok else "编译失败") + "：" + message)
        self._append_log("")
        self._append_log(("=== 编译通过 ===" if ok else "=== 编译失败 ===") + f" {message}")

        module_id = "mod_001"
        mods = self.session.spec.get("modules", [])
        if mods and isinstance(mods[0], dict) and mods[0].get("id"):
            module_id = str(mods[0]["id"])
        result = hvigor.BuildResult(ok=ok, summary=message, hap_path=hap)
        hvigor.append_build_log(self.session, module_id, result)
        self.refresh()
        # 运行部署要求：任务完成（编译出 HAP）后如设置了自动关机，弹倒计时确认
        if ok:
            from wbox.gui.settings import maybe_shutdown_on_finish
            maybe_shutdown_on_finish(app_config.load(), self)

    # ------------------------------------------------------------ 缝状态板

    def _save_seam_edit(self) -> None:
        try:
            self.session.save("缝状态编辑")
        except Exception as e:  # noqa: BLE001
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "保存失败", str(e))

    def _on_seam_changed(self, item: QTableWidgetItem) -> None:
        """文本单元（来源/影响/验证结果/规则更新）编辑后写回并落盘。"""
        seam = item.data(Qt.ItemDataRole.UserRole)
        if not seam:
            return
        col = item.column()
        text = item.text().strip()
        if col == 2:
            seam["source"] = text
        elif col == 3:
            seam["impact"] = text
        elif col == 5:
            seam["verify_result"] = text
        elif col == 6:
            seam["rule_update"] = text
        else:
            return
        self._save_seam_edit()

    def _on_type_combo(self, cb: QComboBox) -> None:
        seam = cb.property("seam")
        if not seam:
            return
        seam["type"] = str(cb.currentData())
        self._save_seam_edit()

    def _on_status_combo(self, cb: QComboBox) -> None:
        seam = cb.property("seam")
        if not seam:
            return
        new_status = str(cb.currentData())
        seam["status"] = new_status
        self._color_status_combo(cb, new_status)
        self._save_seam_edit()

    def _color_status_combo(self, cb: QComboBox, status: str) -> None:
        cb.setStyleSheet(f"color: {_status_color_hex(status)}; font-weight: bold;")

    def _add_seam(self) -> None:
        seam_id = self.session.next_id("seams", "seam_")
        new_seam = {
            "id": seam_id, "type": "logic",
            "source": "（待填写来源）", "impact": "（待填写影响）",
            "status": "open",
        }
        self.session.seams.append(new_seam)
        self.session.save("新增缝")
        self._refresh_seams()
        n = len(self.session.seams)
        if n:
            self.seam_table.selectRow(n - 1)
        self.seam_bar_status.setText(f"已新增 {seam_id}（来源/影响请双击填写）")

    def _del_seam(self) -> None:
        row = self.seam_table.currentRow()
        if row < 0:
            self.seam_bar_status.setText("请先选中要删除的缝行（点行首选中）")
            return
        seams = self.session.seams
        if 0 <= row < len(seams):
            removed = seams.pop(row)
            self.session.save("删除缝")
            self._refresh_seams()
            self.seam_bar_status.setText(f"已删除 {removed.get('id', '')}")

    # ------------------------------------------------------------ 刷新

    def refresh(self) -> None:
        # 目录默认值优先级：⑤装配产出（本工程记忆）> 上次路径 > 工程附近探测 > draft
        if not self.dir_edit.text():
            cfg = app_config.load()
            cand = ""
            remembered = cfg.get("assembled_dirs", {}).get(str(self.session.project_dir), "")
            if remembered and (Path(remembered) / "build-profile.json5").is_file():
                cand = remembered
            else:
                last = cfg.get("tools", {}).get("last_harmony_dir", "")
                if last and (Path(last) / "build-profile.json5").is_file():
                    cand = last
                else:
                    cand = self._probe_harmony_dir()
            self.dir_edit.setText(cand or str(self.session.draft_dir))
        self._update_dir_status()

        # 依赖体检
        tc = dep_mod.resolve_toolchain()
        if tc:
            ver = hvigor.detect_sdk_version(tc.sdk_home)
            self.dep_label.setText(f"工具链就绪：hvigorw + SDK {ver or '?'}（{tc.sdk_home}）")
        else:
            self.dep_label.setText("未检测到命令行工具链（hvigorw+SDK）——「补缝」步需要，可到首页依赖体检一键安装")

        self._refresh_seams()
        self._refresh_log()

    def _probe_harmony_dir(self) -> str:
        """在工程附近找真正可编译的鸿蒙工程（含 build-profile.json5）。

        为什么需要：默认值曾经是 <project>/draft——那是 ArkTS 产物目录，
        没有 build-profile.json5，用户照默认值点编译必然撞
        「不是鸿蒙工程目录」（2026-10-24 用户实测截图）。探测顺序：
        <project>/harmony/* → <project>/harmony → 上两级 harmony/*。
        """
        project = self.session.project_dir
        candidates: list[Path] = []
        harmony = project / "harmony"
        if harmony.is_dir():
            candidates.extend(sorted(p for p in harmony.iterdir() if p.is_dir()))
            candidates.append(harmony)
        for up in (project.parent, project.parent.parent):
            h = up / "harmony"
            if h.is_dir():
                candidates.extend(sorted(p for p in h.iterdir() if p.is_dir()))
        for c in candidates:
            if (c / "build-profile.json5").is_file():
                return str(c)
        return ""

    def _update_dir_status(self) -> None:
        """工程目录有效性实时提示：不是工程时红字引导，避免用户盲点编译。"""
        text = self.dir_edit.text().strip()
        if not text:
            self.status.setText("请先选择鸿蒙工程目录（含 build-profile.json5）")
            return
        if not (Path(text) / "build-profile.json5").is_file():
            self.status.setText(
                "⚠ 该目录不是鸿蒙工程（缺 build-profile.json5）——"
                "draft/ 是 ArkTS 产物目录，请选真实工程根")
        else:
            self.status.setText("")

    def _refresh_seams(self) -> None:
        seams = self.session.seams
        self.seam_table.blockSignals(True)
        self.seam_table.clear()
        self.seam_table.setRowCount(len(seams))
        self.seam_table.setColumnCount(7)
        self.seam_table.setHorizontalHeaderLabels(
            ["ID", "类型", "来源（原版行为/逻辑）", "影响", "状态", "验证结果", "规则更新"])
        hh = self.seam_table.horizontalHeader()
        hh.setSectionResizeMode(0, hh.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, hh.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, hh.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, hh.ResizeMode.Stretch)
        hh.setSectionResizeMode(4, hh.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(5, hh.ResizeMode.Stretch)
        hh.setSectionResizeMode(6, hh.ResizeMode.Stretch)
        for r, seam in enumerate(seams):
            status = seam.get("status", "open")
            type_cn = _TYPE_CN.get(seam.get("type", ""), seam.get("type", ""))
            status_cn = _STATUS_CN.get(status, status)
            # 文本单元（来源/影响/验证结果/规则更新 双击可编辑；其余只读）
            text_cells = {
                0: seam.get("id", ""),
                1: type_cn,
                2: seam.get("source", ""),
                3: seam.get("impact", ""),
                4: status_cn,
                5: seam.get("verify_result", ""),
                6: seam.get("rule_update", ""),
            }
            for c, text in text_cells.items():
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, seam)
                item.setToolTip(text)
                if c in (2, 3, 5, 6):
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                else:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.seam_table.setItem(r, c, item)
            # 类型下拉（第 1 列，覆盖文本单元）
            type_combo = QComboBox()
            for tkey, tcn in _TYPE_CN.items():
                type_combo.addItem(tcn, tkey)
            idx = type_combo.findData(seam.get("type", ""))
            if idx >= 0:
                type_combo.setCurrentIndex(idx)
            type_combo.setProperty("seam", seam)
            type_combo.currentIndexChanged.connect(
                lambda _i, cb=type_combo: self._on_type_combo(cb))
            self.seam_table.setCellWidget(r, 1, type_combo)
            # 状态下拉（第 4 列，覆盖文本单元，按主题色着色）
            status_combo = QComboBox()
            for skey, scn in _STATUS_CN.items():
                status_combo.addItem(scn, skey)
            idx = status_combo.findData(status)
            if idx >= 0:
                status_combo.setCurrentIndex(idx)
            self._color_status_combo(status_combo, status)
            status_combo.setProperty("seam", seam)
            status_combo.currentIndexChanged.connect(
                lambda _i, cb=status_combo: self._on_status_combo(cb))
            self.seam_table.setCellWidget(r, 4, status_combo)
        self.seam_table.resizeRowsToContents()
        self.seam_table.blockSignals(False)
        self.seam_bar_status.setText(
            f"共 {len(seams)} 条缝：状态/类型点下拉切换，来源/影响/验证/规则双击编辑")

    def _refresh_log(self) -> None:
        entries = self.session.build_log
        self.log_table.clear()
        self.log_table.setRowCount(len(entries))
        self.log_table.setColumnCount(4)
        self.log_table.setHorizontalHeaderLabels(["时间", "动作", "摘要", "产物路径"])
        hh = self.log_table.horizontalHeader()
        hh.setSectionResizeMode(0, hh.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, hh.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, hh.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, hh.ResizeMode.Stretch)
        _ACTION_CN = {
            "extracted": "拆", "draft_generated": "填上", "compile_verified": "编译通过",
            "human_edited": "人工修改", "confirmed": "确认", "rolled_back": "回滚",
            "runtime_fixed": "修复记录",
        }
        for r, e in enumerate(entries):
            at = str(e.get("at", ""))[:19].replace("T", " ")
            action = _ACTION_CN.get(e.get("action", ""), e.get("action", ""))
            summary = str(e.get("summary", ""))
            for c, text in enumerate([at, action, summary, e.get("diff_ref", "")]):
                item = QTableWidgetItem(text)
                # 摘要不再预截断：tooltip 全文 + 全局 setWordWrap（2026-10-25）
                item.setToolTip(text)
                self.log_table.setItem(r, c, item)
        self.log_table.resizeRowsToContents()

    def on_enter(self) -> None:
        self.refresh()
