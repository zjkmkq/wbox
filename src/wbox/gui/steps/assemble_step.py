"""wbox.gui.steps.assemble_step —— ⑤ 装配：draft/ + 资源 + 骨架 → 可编译鸿蒙工程。

定位（用户实测断档）：
  ④ 填上 产出的是 draft/ 下的 ArkTS 草案文件——它们不是工程，不能直接编译，
  也不该直接拿去测。过去要先用 CLI `python -m wbox.assemble` 把 draft 变成
  真正可编译的鸿蒙工程，再手动指给 ⑥ 补缝。这条链路以前只藏在 CLI，现在进了 GUI。

  本步把装配搬进 GUI，并自动把产物目录喂给 ⑥ 补缝（写回配置，⑥ 默认即指向它）。

流程（写死）：
  读 draft/（④ 填上产物）→ [开始装配] → _AssembleWorker 后台跑 assemble_project
  → 成功：产出鸿蒙工程目录（含 build-profile.json5 / module.json5 / EntryAbility /
    main_pages.json / ArkTS 代码 / rawfile 资源），按钮可打开工程目录 / 用 DevEco 打开
  → 失败：日志区报错。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from wbox import assemble as assemble_mod
from wbox import config as app_config
from wbox.ascii_names import harmony_default_dir
from wbox.gui.session import ProjectSession
from wbox.gui.steps import StepPage, register


class _AssembleWorker(QThread):
    """后台跑 assemble_project；日志逐行抛出，结束抛结果。"""

    log_line = Signal(str)
    finished = Signal(bool, str, str)   # ok, message, project_dir

    def __init__(self, spec_path: str, draft_dir: str, out_dir: str) -> None:
        super().__init__()
        self.spec_path = spec_path
        self.draft_dir = draft_dir
        self.out_dir = out_dir

    def run(self) -> None:
        try:
            r = assemble_mod.assemble_project(
                self.spec_path, self.draft_dir, self.out_dir,
                on_log=lambda m: self.log_line.emit(m))
        except Exception as e:  # noqa: BLE001
            self.finished.emit(False, f"异常：{e}", "")
            return
        if not r.ok:
            self.finished.emit(False, r.error, r.project_dir or "")
            return
        msg = (f"代码 {len(r.code_files)} 个 / 资源 {len(r.resource_files)} 项 / "
               f"页面 {len(r.pages)} 个（主页面 {r.main_page}）"
               + ("　[Web 壳工程]" if r.web_shell else ""))
        if r.missing_resources:
            msg += f"；缺失资源 {len(r.missing_resources)} 项（前 5：{'、'.join(r.missing_resources[:5])}）"
        self.finished.emit(True, msg, r.project_dir)


@register
class AssembleStep(StepPage):
    step_id = "assemble"
    title = "⑤ 装配"
    subtitle = "把「④ 填上」的 ArkTS 草案 + 资源 + 骨架模板，装配成真正可编译的鸿蒙工程（正式工程文件）"

    # ------------------------------------------------------------ 构建

    def _build_body(self) -> None:
        intro = QLabel(
            "本步把 draft/ 里的 ArkTS 草案文件，连同资源与工程骨架，装配成 DevEco Studio "
            "可直接打开/编译的鸿蒙工程。装配完成后，下一步「⑥ 补缝」会自动指向本工程。")
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        self.body.addWidget(intro)

        # 输出目录行
        bar = QHBoxLayout()
        bar.addWidget(QLabel("鸿蒙工程输出目录："))
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText("默认 <工程>/harmony/<应用名>")
        bar.addWidget(self.dir_edit, stretch=1)
        self.btn_browse = QPushButton("浏览…")
        self.btn_browse.clicked.connect(self._browse)
        bar.addWidget(self.btn_browse)
        self.body.addLayout(bar)

        # 操作行
        act = QHBoxLayout()
        self.btn_assemble = QPushButton("开始装配")
        self.btn_assemble.setObjectName("primary")
        self.btn_assemble.clicked.connect(self._start)
        act.addWidget(self.btn_assemble)
        self.status = QLabel("")
        act.addWidget(self.status, stretch=1)
        self.body.addLayout(act)

        # 日志
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(4000)
        self.console.setStyleSheet("font-family: Consolas, 'Courier New', monospace;")
        self.body.addWidget(self.console, stretch=2)

        # 结果说明
        self.result = QLabel("")
        self.result.setWordWrap(True)
        self.result.setObjectName("muted")
        self.body.addWidget(self.result)

        # 结果按钮行
        res_bar = QHBoxLayout()
        self.btn_open_dir = QPushButton("打开工程目录")
        self.btn_open_dir.clicked.connect(self._open_explorer)
        self.btn_open_deveco = QPushButton("用 DevEco Studio 打开")
        self.btn_open_deveco.clicked.connect(self._open_deveco)
        self.btn_reassemble = QPushButton("重新装配")
        self.btn_reassemble.clicked.connect(self._start)
        self.btn_next = QPushButton("前往 ⑥ 补缝 →")
        self.btn_next.setObjectName("primary")
        self.btn_next.clicked.connect(lambda: self.navigate.emit("seal"))
        for b in (self.btn_open_dir, self.btn_open_deveco, self.btn_reassemble, self.btn_next):
            b.setVisible(False)
        res_bar.addWidget(self.btn_open_dir)
        res_bar.addWidget(self.btn_open_deveco)
        res_bar.addWidget(self.btn_reassemble)
        res_bar.addStretch(1)
        res_bar.addWidget(self.btn_next)
        self.body.addLayout(res_bar)

        self._worker: _AssembleWorker | None = None
        self._last_project_dir = ""

    # ------------------------------------------------------------ 动作

    def _browse(self) -> None:
        start = self.dir_edit.text() or str(self.session.project_dir)
        d = QFileDialog.getExistingDirectory(self, "选择鸿蒙工程输出目录", start)
        if not d:
            return
        self.dir_edit.setText(d)

    def _draft_ets_count(self) -> int:
        d = self.session.draft_dir
        if not d.is_dir():
            return 0
        return sum(1 for _ in d.rglob("*.ets"))

    def _default_out_dir(self) -> str:
        app_name = self.session.project_name
        out, _note = harmony_default_dir(self.session.project_dir, app_name)
        return str(out)

    def _start(self) -> None:
        if self._draft_ets_count() == 0:
            self.status.setText("⚠ draft/ 为空（先完成「④ 填上」生成 ArkTS 草案）")
            return
        out = self.dir_edit.text().strip() or self._default_out_dir()
        self.dir_edit.setText(out)
        self.btn_assemble.setEnabled(False)
        for b in (self.btn_open_dir, self.btn_open_deveco, self.btn_reassemble, self.btn_next):
            b.setVisible(False)
        self.result.setText("")
        self.status.setText("装配中…")
        self.console.clear()
        self._worker = _AssembleWorker(
            str(self.session.spec_path), str(self.session.draft_dir), out)
        self._worker.log_line.connect(self._append_log)
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    def _append_log(self, line: str) -> None:
        self.console.appendPlainText(line)

    def _on_done(self, ok: bool, message: str, project_dir: str) -> None:
        self.btn_assemble.setEnabled(True)
        self._append_log("")
        if ok:
            self._last_project_dir = project_dir
            self.status.setText("✓ 装配完成（已生成可编译鸿蒙工程）")
            self.result.setText(
                "✓ " + message + "\n"
                "工程目录：" + project_dir + "\n"
                "下一步到「⑥ 补缝」编译验证；本目录已自动填好。")
            for b in (self.btn_open_dir, self.btn_open_deveco, self.btn_reassemble, self.btn_next):
                b.setVisible(True)
            self._remember(project_dir)
        else:
            self.status.setText("✗ 装配失败：" + message[:80])
            self.result.setText("✗ " + message)
        self._append_log(("=== 装配完成 ===" if ok else "=== 装配失败 ===") + " " + message)

    def _remember(self, project_dir: str) -> None:
        """把装配产物目录写回配置，让 ⑥ 补缝 自动指向它。

        spec 契约顶层 additionalProperties=false，不能塞自定义键；配置（config.json）
        是宽松的，用它存工程→装配目录映射，避免多工程串味。同时更新
        tools.last_harmony_dir（⑥ 的兜底默认值）。
        """
        cfg = app_config.load()
        key = str(self.session.project_dir)
        cfg.setdefault("assembled_dirs", {})[key] = project_dir
        cfg.setdefault("tools", {})["last_harmony_dir"] = project_dir
        try:
            app_config.save(cfg)
        except Exception:  # noqa: BLE001  写配置失败不阻断主流程
            pass

    # ------------------------------------------------------------ 打开

    def _open_explorer(self) -> None:
        if not self._last_project_dir:
            return
        try:
            os.startfile(self._last_project_dir)   # noqa: S606  打开资源管理器
        except Exception as e:  # noqa: BLE001
            self.status.setText(f"打开失败：{e}")

    def _open_deveco(self) -> None:
        if not self._last_project_dir:
            return
        exe = self._find_deveco()
        if not exe:
            self.status.setText("未找到 DevEco Studio（将在工程目录打开，你手动拖入 IDE 亦可）")
            self._open_explorer()
            return
        try:
            subprocess.Popen([exe, self._last_project_dir])   # noqa: S603
        except Exception as e:  # noqa: BLE001
            self.status.setText(f"启动 DevEco 失败：{e}")

    @staticmethod
    def _find_deveco() -> str:
        """常见安装位置探测 DevEco Studio 可执行文件。"""
        candidates = [
            r"D:\Office_Tools\DevEco Studio\bin\devecostudio64.exe",
            r"D:\Office_Tools\DevEco Studio\bin\deveostudio.exe",
            r"C:\Program Files\Huawei\DevEco Studio\bin\devecostudio64.exe",
            r"C:\Program Files\Huawei\DevEco Studio\bin\deveostudio.exe",
        ]
        for c in candidates:
            if Path(c).is_file():
                return c
        return ""

    # ------------------------------------------------------------ 进入/刷新

    def refresh(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return  # 装配进行中不抢界面
        if not self.dir_edit.text():
            cfg = app_config.load()
            remembered = cfg.get("assembled_dirs", {}).get(str(self.session.project_dir), "")
            self.dir_edit.setText(remembered or self._default_out_dir())
        n = self._draft_ets_count()
        if n == 0:
            self.status.setText("draft/ 为空（先完成「④ 填上」生成 ArkTS 草案）")
        else:
            self.status.setText(f"draft/ 现有 {n} 个 ArkTS 文件，可开始装配")

    def on_enter(self) -> None:
        self.refresh()
