"""wbox.gui.steps.extract_step —— ① 拆：APK → spec 三段清单（GUI 实跑版）。

流程（写死）：
  解析工具路径（deps）→ apktool 流式解包（worker 线程，日志实时进界面）
  → build_spec 组装 → 合并旧人工记录（decisions/seams 保留，build_log 追加）
  → wbox.spec.save 落盘 → 主窗重载会话刷新三栏。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from wbox import config as app_config
from wbox import deps as dep_mod
from wbox.ascii_names import work_dir_name
from wbox.extract import ExtractError, build_spec, merge_manual_records
from wbox.gui.session import ProjectSession
from wbox.gui.steps import StepPage, register
from wbox.gui import theme
from wbox.spec import load, save


class _ExtractWorker(QThread):
    """后台跑 apktool + build_spec + save；日志逐行抛出。"""

    log_line = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, apk: Path, work_dir: Path, spec_path: Path, java: str, jar: str) -> None:
        super().__init__()
        self.apk = apk
        self.work_dir = work_dir
        self.spec_path = spec_path
        self.java = java
        self.jar = jar

    def run(self) -> None:
        try:
            self._run_apktool()
            self.log_line.emit("解析资源与代码骨架…")
            new_spec = build_spec(self.apk, self.work_dir)
            if self.spec_path.exists():
                new_spec = merge_manual_records(new_spec, load(self.spec_path))
            save(new_spec, self.spec_path)
            entry = new_spec["build_log"][-1]
            summary = entry.get("summary", "")
            self.log_line.emit(f"完成：{summary}")
            self.finished.emit(True, summary)
        except Exception as e:  # noqa: BLE001  worker 内兜底，任何失败都要报告
            self.log_line.emit(f"失败：{e}")
            self.finished.emit(False, str(e))

    def _run_apktool(self) -> None:
        self.work_dir.parent.mkdir(parents=True, exist_ok=True)
        cmd = [self.java, "-jar", self.jar, "d", str(self.apk), "-o", str(self.work_dir), "-f"]
        self.log_line.emit(" ".join(cmd))
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace", bufsize=1)
        assert proc.stdout is not None
        for line in proc.stdout:
            self.log_line.emit(line.rstrip())
        code = proc.wait()
        if code != 0:
            raise ExtractError(f"apktool 解包失败（退出码 {code}）")
        if not (self.work_dir / "AndroidManifest.xml").exists():
            raise ExtractError(f"解包目录不完整（缺 AndroidManifest.xml）：{self.work_dir}")


@register
class ExtractStep(StepPage):
    step_id = "extract"
    title = "① 拆"
    subtitle = "APK → 资源清单 / 模块骨架 / 行为骨架（apktool 实跑，只做机器可推导的部分）"

    def __init__(self, session: ProjectSession, parent=None) -> None:
        super().__init__(session, parent)
        self._worker: _ExtractWorker | None = None

    # ------------------------------------------------------------ UI

    def _build_body(self) -> None:
        row = QHBoxLayout()
        row.addWidget(QLabel("APK："))
        self.apk_edit = QLabel("")
        self.apk_edit.setStyleSheet(f"color:{theme.C_INFO_TXT};")
        row.addWidget(self.apk_edit, stretch=1)
        btn_browse = QPushButton("浏览…")
        btn_browse.clicked.connect(self._browse_apk)
        row.addWidget(btn_browse)
        self.body.addLayout(row)

        self.work_label = QLabel("")
        self.work_label.setObjectName("muted")
        self.body.addWidget(self.work_label)

        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        self.body.addWidget(self.summary_label)

        btn_row = QHBoxLayout()
        self.btn_run = QPushButton("开始拆解")
        self.btn_run.setObjectName("primary")
        self.btn_run.clicked.connect(self._run)
        btn_row.addWidget(self.btn_run)
        btn_row.addStretch(1)
        self.body.addLayout(btn_row)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.body.addWidget(self.log, stretch=1)

    def refresh(self) -> None:
        src = str(self.session.spec.get("project", {}).get("source", ""))
        self.apk_edit.setText(src or "（未记录 APK 路径）")
        work_name = work_dir_name(Path(src).stem) if src else ""
        self.work_label.setText(f"解包目录：{self.session.work_dir / work_name if work_name else self.session.work_dir}"
                               + ("" if not src or work_name == Path(src).stem else "（已按英文目录存放，DevEco 不识别中文目录）"))
        n = len(self.session.resources)
        m = len(self.session.modules)
        b = len(self.session.behaviors)
        self.summary_label.setText(
            f"当前清单：资源 {n} 条 / 模块 {m} 个 / 行为 {b} 条"
            + ("" if (n or m or b) else "（尚未拆解）")
        )

    def on_enter(self) -> None:
        self.refresh()

    # ------------------------------------------------------------ 动作

    def _browse_apk(self) -> None:
        start = str(self.session.spec.get("project", {}).get("source", "")) or ""
        apk, _ = QFileDialog.getOpenFileName(self, "选择 APK", start, "APK (*.apk)")
        if not apk:
            return
        self.session.spec.setdefault("project", {})["source"] = apk
        self.session.update("更新 APK 路径")
        self.refresh()

    def _run(self) -> None:
        cfg = app_config.load()
        status = {s.id: s for s in dep_mod.check_all(cfg)}
        if not status["java"].ok:
            self.log.appendPlainText("Java 未就绪：请回首页「依赖体检」一键安装 JDK 17。")
            return
        jar = dep_mod.apktool_jar(cfg)
        if not jar:
            self.log.appendPlainText("apktool 未就绪：请回首页「依赖体检」安装。")
            return
        src = str(self.session.spec.get("project", {}).get("source", ""))
        if not src or not Path(src).is_file():
            self.log.appendPlainText("APK 路径无效，请先浏览选择有效的 .apk 文件。")
            return

        self.btn_run.setEnabled(False)
        self.log.clear()
        self.log.appendPlainText(f"APK：{src}")
        # 解包目录 ASCII 化：中文 APK 名 → 英文目录（DevEco 不认中文目录）
        work = self.session.work_dir / work_dir_name(Path(src).stem)
        self._worker = _ExtractWorker(Path(src), work, self.session.spec_path,
                                      dep_mod.java_bin(cfg), jar)
        self._worker.log_line.connect(self.log.appendPlainText)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_finished(self, ok: bool, message: str) -> None:
        self.btn_run.setEnabled(True)
        if ok:
            # 从磁盘重载会话（worker 已落盘），刷新三栏
            self.session.load()
            self.session.changed.emit("拆解完成")
        else:
            self.log.appendPlainText(f"拆解失败：{message}")
