"""wbox.gui.pages.tools —— 工具箱：编译 / 装机 / 启动 / 截图 / 巡检 / 探针按钮化。

存在理由：这些能力以前只存在于命令行（scripts/verify_device.py、wbox.hvigor），
要求用户记命令、看终端。本页把它们变按钮：左边选工程与设备，右边点一下就跑，
日志流式滚出来。所有重活都在 QThread 子类的 run() 里，UI 不卡。

诚实原则（写死）：缺 hdc / hvigor / node 时按钮**直接禁用并在 tooltip 说明缺什么**，
不做"点了才报错"，也不假装能用。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from wbox import deps as dep_mod
from wbox import toolchain as toolchain_mod
from wbox.gui.session import ProjectSession
from wbox.gui.threads import track_thread
from wbox.gui.uikit import harden_window, plain_text, wrap_label

_TASK_BUTTONS = ("build", "install", "start", "snapshot", "inspect", "probe")


class _TaskThread(QThread):
    """跑一个 toolchain 调用：日志逐行发信号，完成后回一条结论。

    硬规则：工作放 run()，不用 moveToThread + quit 那套（quit 会丢，进程退不出）。
    """

    log = Signal(str)
    done = Signal(bool, str)

    def __init__(self, fn: Callable[[Callable[[str], None]], object], parent=None) -> None:
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            result = self._fn(self.log.emit)
            ok = bool(getattr(result, "ok", False))
            text = result.as_text() if hasattr(result, "as_text") else str(result)
            self.done.emit(ok, text)
        except Exception as e:  # noqa: BLE001  绝不让任务异常炸掉 UI
            self.done.emit(False, f"任务异常：{e}")


class _ListTargetsThread(QThread):
    """列出可用设备。

    单独一个线程类而不是复用 _TaskThread：设备列表要在 **GUI 线程**里回填
    （早期版本在 worker 里直接 `dev_list.addItem()`，跨线程碰 QWidget，随机崩）。
    """

    log = Signal(str)
    found = Signal(list)
    failed = Signal(str)

    def __init__(self, cfg: dict, parent=None) -> None:
        super().__init__(parent)
        self._cfg = cfg

    def run(self) -> None:
        try:
            devices, raw = toolchain_mod.list_targets(cfg=self._cfg, on_line=self.log.emit)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))
            return
        lines = [d.as_text() for d in devices]
        if lines:
            self.found.emit(lines)
        else:
            self.failed.emit("未发现设备（hdc list targets 为空）\n" + raw[-800:])


class _ProbeCompareDialog(QDialog):
    """两张探针图并排摆：左=WebGL 原样跑，右=拦掉 WebGL 强制 Canvas2D。

    存在理由：迁移排障最常见的判断是"到底能不能用 WebGL"。两张图放一起，
    一眼就能看出回落之后有没有糊/缺层——这是把 scripts/ 里的手工对照变成按钮。
    """

    def __init__(self, normal: Path, canvas: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("浏览器探针：WebGL vs Canvas 回落")
        self.resize(1180, 720)
        lay = QVBoxLayout(self)
        tip = wrap_label(
            "同一 URL 跑两遍：左图保留 WebGL，右图拦掉 getContext('webgl') 强制回落 Canvas2D。\n"
            "两图不一致 → 说明这份 H5 依赖 WebGL，ArkWeb 上白屏基本就是它。",
            object_name="muted")
        lay.addWidget(tip)

        row = QHBoxLayout()
        for title, path in (("左：WebGL（normal）", normal), ("右：Canvas 回落（canvas）", canvas)):
            col = QVBoxLayout()
            head = QLabel(title)
            head.setObjectName("h2")
            col.addWidget(head)
            view = QLabel()
            view.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pix = QPixmap(str(path))
            if pix.isNull():
                view.setText(f"无法解码：{path}")
            else:
                view.setPixmap(pix.scaled(560, 560, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))
                view.setToolTip(f"{path.name}　{pix.width()}×{pix.height()}")
            col.addWidget(view, stretch=1)
            row.addLayout(col, stretch=1)
        lay.addLayout(row, stretch=1)

        bar = QHBoxLayout()
        bar.addStretch(1)
        btn = QPushButton("关闭")
        btn.clicked.connect(self.accept)
        bar.addWidget(btn)
        lay.addLayout(bar)
        harden_window(self)


class ToolsPage(QWidget):
    """工具箱页面。"""

    back = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session: ProjectSession | None = None
        self._thread: _TaskThread | None = None
        self._dev_thread: _ListTargetsThread | None = None
        self._server: object | None = None        # 本地静态服务（起过就不再重复起）
        self._probe_tag = ""
        self._device_count: int | None = None     # None=尚未确认，0=确定没有设备
        self._hdc = ""
        self._hvigor_ok = False
        self._node = ""
        self._last_artifact = ""

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)

        head = QHBoxLayout()
        btn_back = QPushButton("← 返回工作区")
        btn_back.clicked.connect(self.back.emit)
        head.addWidget(btn_back)
        title = QLabel("工具箱")
        title.setObjectName("h1")
        head.addWidget(title)
        head.addStretch(1)
        self.env_label = QLabel("正在检测本机工具…")
        self.env_label.setObjectName("muted")
        head.addWidget(self.env_label)
        lay.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self._build_left(), stretch=0)
        body.addWidget(self._build_right(), stretch=1)
        lay.addLayout(body, stretch=1)

        harden_window(self)
        self.refresh_env()

    # ------------------------------------------------------------ 左栏

    def _build_left(self) -> QWidget:
        col = QWidget()
        col.setMinimumWidth(360)
        col.setMaximumWidth(520)
        lay = QVBoxLayout(col)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        # 工程
        gb_proj = QGroupBox("鸿蒙工程（编译对象）")
        fm = QVBoxLayout(gb_proj)
        self.edit_project = QLineEdit()
        self.edit_project.setPlaceholderText("含 build-profile.json5 的工程根目录")
        fm.addWidget(self.edit_project)
        row = QHBoxLayout()
        btn_pick = QPushButton("浏览…")
        btn_pick.clicked.connect(self._pick_project)
        btn_auto = QPushButton("用当前工程")
        btn_auto.setToolTip("自动定位当前迁移工程装配出来的鸿蒙工程（…/harmony/<应用名>）")
        btn_auto.clicked.connect(self._autofill_from_session)
        row.addWidget(btn_pick)
        row.addWidget(btn_auto)
        row.addStretch(1)
        fm.addLayout(row)

        hap_row = QHBoxLayout()
        self.edit_hap = QLineEdit()
        self.edit_hap.setPlaceholderText("HAP 路径（编译成功后自动填入）")
        btn_hap = QPushButton("浏览…")
        btn_hap.clicked.connect(self._pick_hap)
        hap_row.addWidget(self.edit_hap, stretch=1)
        hap_row.addWidget(btn_hap)
        fm.addLayout(hap_row)
        lay.addWidget(gb_proj)

        # 设备
        gb_dev = QGroupBox("设备与目标应用")
        dv = QVBoxLayout(gb_dev)
        dev_row = QHBoxLayout()
        self.btn_devices = QPushButton("刷新设备")
        self.btn_devices.clicked.connect(self._refresh_devices)
        dev_row.addWidget(self.btn_devices)
        dev_row.addStretch(1)
        dv.addLayout(dev_row)
        self.dev_list = QListWidget()
        self.dev_list.setMaximumHeight(84)
        dv.addWidget(self.dev_list)
        self.hdc_label = QLabel("hdc：检测中…")
        self.hdc_label.setObjectName("muted")
        dv.addWidget(self.hdc_label)

        self.edit_bundle = QLineEdit()
        self.edit_bundle.setPlaceholderText("bundleName，如 com.example.game")
        dv.addWidget(self.edit_bundle)
        ability_row = QHBoxLayout()
        self.edit_ability = QLineEdit("EntryAbility")
        self.edit_ability.setToolTip("入口 Ability 名，默认 EntryAbility")
        ability_row.addWidget(QLabel("Ability："))
        ability_row.addWidget(self.edit_ability, stretch=1)
        dv.addLayout(ability_row)

        wait_row = QHBoxLayout()
        self.spin_wait = QDoubleSpinBox()
        self.spin_wait.setRange(0.0, 600.0)
        self.spin_wait.setValue(15.0)
        self.spin_wait.setSuffix(" 秒")
        self.spin_wait.setToolTip("启动后等多久再截图：程序化生成首帧的包要 15~25 秒")
        wait_row.addWidget(QLabel("首帧等待："))
        wait_row.addWidget(self.spin_wait, stretch=1)
        dv.addLayout(wait_row)

        tap_row = QHBoxLayout()
        self.edit_taps = QLineEdit()
        self.edit_taps.setPlaceholderText("巡检点击序列（可选）：637,1158;1416,1158")
        self.edit_taps.setToolTip("分号分隔的 x,y 坐标；每点一次截一张图")
        tap_row.addWidget(self.edit_taps, stretch=1)
        dv.addLayout(tap_row)
        lay.addWidget(gb_dev)

        self.help_label = wrap_label(
            "提示：编译产物是 unsigned HAP（签名归 DevEco IDE）；装机前请确认设备已连上、"
            "且已在设备上信任本机调试。", object_name="muted")
        lay.addWidget(self.help_label)
        lay.addStretch(1)
        return col

    # ------------------------------------------------------------ 右栏

    def _build_right(self) -> QWidget:
        col = QWidget()
        lay = QVBoxLayout(col)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        gb_act = QGroupBox("操作")
        grid = QGridLayout(gb_act)
        grid.setSpacing(8)
        self.btn: dict[str, QPushButton] = {}
        self._tips: dict[str, str] = {}
        specs = [
            ("build", "① 编译工程", "hvigor assembleHap：把工程编译成 HAP", self._run_build),
            ("install", "② 装机", "推送 HAP 到设备并 bm install", self._run_install),
            ("start", "③ 启动应用", "aa force-stop + aa start 重启应用", self._run_start),
            ("snapshot", "④ 截图", "设备整屏截图并拉回本机", self._run_snapshot),
            ("inspect", "⑤ 一键巡检", "装机 → 启动 → 等首帧 → 截图（可选点击巡检）", self._run_inspect),
            ("probe", "⑥ 浏览器探针", "用 Node 对 URL 截图，供与真机逐像素比对", self._run_probe),
        ]
        for i, (key, text, tip, slot) in enumerate(specs):
            btn = QPushButton(text)
            btn.setToolTip(tip)
            if key in ("build", "inspect"):
                btn.setObjectName("primary")
            btn.clicked.connect(slot)
            self.btn[key] = btn
            self._tips[key] = tip
            grid.addWidget(btn, i // 3, i % 3)

        probe_row = QHBoxLayout()
        self.edit_url = QLineEdit()
        self.edit_url.setPlaceholderText("探针页面 URL（如 http://127.0.0.1:8791/index.html）")
        probe_row.addWidget(self.edit_url, stretch=1)
        self.btn_serve = QPushButton("起本地服务")
        self.btn_serve.setToolTip("用 python -m http.server 把当前工程资源目录起成 URL（H5 常是相对路径，file:// 打不开）")
        self.btn_serve.clicked.connect(self._start_server)
        probe_row.addWidget(self.btn_serve)
        grid.addLayout(probe_row, 2, 0, 1, 3)

        open_row = QHBoxLayout()
        self.btn_open_artifact = QPushButton("打开产物")
        self.btn_open_artifact.setEnabled(False)
        self.btn_open_artifact.clicked.connect(self._open_artifact)
        self.btn_open_dir = QPushButton("打开产物目录")
        self.btn_open_dir.clicked.connect(self._open_artifact_dir)
        open_row.addWidget(self.btn_open_artifact)
        open_row.addWidget(self.btn_open_dir)
        open_row.addStretch(1)
        grid.addLayout(open_row, 3, 0, 1, 3)
        lay.addWidget(gb_act)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setTextVisible(True)
        lay.addWidget(self.progress)

        log_head = QHBoxLayout()
        log_title = QLabel("运行日志")
        log_title.setObjectName("h2")
        log_head.addWidget(log_title)
        log_head.addStretch(1)
        self.btn_cancel = QPushButton("中断")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setToolTip("终止正在跑的子进程；多步任务在下一小步止步")
        self.btn_cancel.clicked.connect(self._cancel)
        log_head.addWidget(self.btn_cancel)
        btn_export = QPushButton("导出日志")
        btn_export.setToolTip("把日志存成本地 .log 文件，便于贴给别人复现")
        btn_export.clicked.connect(self._export_log)
        log_head.addWidget(btn_export)
        btn_clear = QPushButton("清空")
        btn_clear.clicked.connect(lambda: self.console.clear())
        log_head.addWidget(btn_clear)
        lay.addLayout(log_head)

        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.console.setMaximumBlockCount(5000)
        self.console.setPlaceholderText("点上面的按钮开始；日志会实时滚在这里。")
        lay.addWidget(self.console, stretch=1)
        return col

    # ------------------------------------------------------------ 环境

    def refresh_env(self) -> None:
        """探测 hdc / hvigor / node 是否就绪，据此禁用按钮并说明缺什么。"""
        cfg = dep_mod.app_config.load()
        self._hdc = toolchain_mod.find_hdc(cfg)
        self._hvigor_ok = dep_mod.resolve_toolchain(cfg) is not None
        self._node = toolchain_mod.find_node()

        # 顶栏只放紧凑徽标（✓/✗），完整状态与路径放 tooltip——否则一行文字会折成三行
        bits = [
            f"hdc {'✓' if self._hdc else '✗'}",
            f"hvigor {'✓' if self._hvigor_ok else '✗'}",
            f"node {'✓' if self._node else '✗'}",
        ]
        self.env_label.setText("　·　".join(bits))
        # 顶栏标签只能占一行：按实际字宽给最小宽度，否则会被 QHBoxLayout 压到折行
        self.env_label.setMinimumWidth(
            self.env_label.fontMetrics().horizontalAdvance(self.env_label.text()) + 16)
        self.env_label.setToolTip(plain_text("\n".join([
            f"hdc：{'已就绪' if self._hdc else '缺失'}",
            f"hvigor：{'已就绪' if self._hvigor_ok else '缺失'}",
            f"node：{'已就绪' if self._node else '缺失'}",
            f"hdc 路径：{self._hdc or '（未找到）'}",
        ])))
        self.hdc_label.setText(f"hdc：{self._hdc or '未找到（设置 → 插件与依赖 安装命令行工具）'}")
        self.hdc_label.setToolTip(self.hdc_label.text())

        self._gate("build", self._hvigor_ok,
                   "编译需要 HarmonyOS 命令行工具链（设置 → 插件与依赖）")
        for key in ("install", "start", "snapshot", "inspect"):
            self._gate(key, bool(self._hdc), "需要 hdc.exe：请安装 HarmonyOS 命令行工具（含 SDK）")
        # 设备状态确定为空时，进一步禁用"必须接设备"的四个动作（无设备时点了只会报错）
        if self._hdc and self._device_count == 0:
            for key in ("install", "start", "snapshot", "inspect"):
                self._gate(key, False, "未检测到设备：请连接真机/启动模拟器后点「刷新设备」")
        # 探针不看 node 有没有，要看"能不能跑全链路"（node + puppeteer-core + Edge）
        probe_ok, probe_why = toolchain_mod.probe_status()
        self._gate("probe", probe_ok, probe_why)
        self.btn_serve.setEnabled(True)
        self.btn_serve.setToolTip("用 python -m http.server 把含 index.html 的目录起成本地 URL"
                                  + ("" if probe_ok else "（探针当前不可用，但起服务无妨）"))

    def _busy(self) -> bool:
        """是否有本页的后台任务在跑（任务线程或刷新设备线程）。"""
        for th in (self._thread, self._dev_thread):
            try:
                if th is not None and th.isRunning():
                    return True
            except RuntimeError:      # 底层 C++ 对象已销毁
                continue
        return False

    def _gate(self, key: str, available: bool, reason: str) -> None:
        btn = self.btn.get(key)
        if btn is None:
            return
        if not available:
            btn.setEnabled(False)
            btn.setToolTip(reason)
            return
        btn.setToolTip(self._tips.get(key, ""))
        btn.setEnabled(not self._busy())

    def _set_running(self, running: bool) -> None:
        self.progress.setVisible(running)
        if running:
            self.progress.setRange(0, 0)
            self.progress.setFormat("执行中…")
        for btn in self.btn.values():
            if running:
                btn.setEnabled(False)
        self.btn_cancel.setEnabled(bool(running))
        if not running:
            self.refresh_env()

    # ------------------------------------------------------------ 会话

    def set_session(self, session: ProjectSession | None) -> None:
        self._session = session
        if session is not None and not self.edit_project.text().strip():
            self._autofill_from_session()

    def _autofill_from_session(self) -> None:
        """从当前迁移工程推断鸿蒙工程目录（…/harmony/<应用名>）与最近的 HAP。"""
        if self._session is None:
            return
        root = self._session.project_dir
        candidates: list[Path] = []
        harmony_root = root / "harmony"
        if harmony_root.is_dir():
            for child in sorted(harmony_root.iterdir()):
                if child.is_dir() and (child / "build-profile.json5").is_file():
                    candidates.append(child)
        if (root / "build-profile.json5").is_file():
            candidates.append(root)
        if candidates:
            self.edit_project.setText(str(candidates[0]))
        hap = self._find_hap(candidates[0] if candidates else root)
        if hap:
            self.edit_hap.setText(hap)
        bundle = self._guess_bundle(candidates[0] if candidates else root)
        if bundle and not self.edit_bundle.text().strip():
            self.edit_bundle.setText(bundle)

    @staticmethod
    def _find_hap(project: Path) -> str:
        from wbox import hvigor as hvigor_mod

        try:
            return hvigor_mod._find_hap(project)      # noqa: SLF001  同一项目内复用
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _guess_bundle(project: Path) -> str:
        """从 AppScope/app.json5 里猜 bundleName（猜不到就留空，让用户自己填）。"""
        for rel in ("AppScope/app.json5", "entry/src/main/module.json5"):
            path = project / rel
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                if "bundleName" in line and ":" in line:
                    value = line.split(":", 1)[1].strip().strip(",").strip()
                    value = value.strip('"').strip("'")
                    if value and "$" not in value:
                        return value
        return ""

    # ------------------------------------------------------------ 选择

    def _pick_project(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择鸿蒙工程根目录（含 build-profile.json5）")
        if d:
            self.edit_project.setText(d)
            hap = self._find_hap(Path(d))
            if hap:
                self.edit_hap.setText(hap)

    def _pick_hap(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 HAP", "", "HAP (*.hap);;所有文件 (*.*)")
        if path:
            self.edit_hap.setText(path)

    # ------------------------------------------------------------ 任务框架

    def _start(self, fn) -> None:
        if self._thread is not None and self._thread.isRunning():
            self._append("[提示] 上一个任务还在跑，等它结束")
            return
        toolchain_mod.reset_cancel()
        self._set_running(True)
        th = track_thread(_TaskThread(fn, self))
        th.log.connect(self._append)
        th.done.connect(self._on_done)
        self._thread = th
        th.start()

    def _append(self, line: str) -> None:
        self.console.appendPlainText(line)

    def _cancel(self) -> None:
        killed = toolchain_mod.cancel_active()
        self._append(f"[中断] 已请求停止，杀掉 {killed} 个子进程；剩余步骤会被跳过")
        self.btn_cancel.setEnabled(False)

    def _export_log(self) -> None:
        text = self.console.toPlainText().strip()
        if not text:
            self._append("[提示] 日志是空的，没什么可导出")
            return
        stamp = time.strftime("%Y%m%d-%H%M%S")
        default = str(self._shots_dir() / f"wbox-tool-{stamp}.log")
        path, _ = QFileDialog.getSaveFileName(self, "导出日志", default, "日志 (*.log);;文本 (*.txt)")
        if not path:
            return
        try:
            Path(path).write_text(text, encoding="utf-8")
        except OSError as e:
            self._append(f"[失败] 写日志出错：{e}")
            return
        self._append(f"✓ 日志已导出：{path}")

    def _on_done(self, ok: bool, message: str) -> None:
        self._append(("✓ " if ok else "✗ ") + message)
        self.progress.setVisible(False)
        self._set_running(False)
        # 编译成功会把 HAP 填进来，巡检成功会把截图路径记下来
        if "产物：" in message:
            artifact = message.split("产物：")[-1].strip()
            if artifact:
                self._last_artifact = artifact
                self.btn_open_artifact.setEnabled(True)
                if artifact.lower().endswith(".hap") and not self.edit_hap.text().strip():
                    self.edit_hap.setText(artifact)
        # 探针跑出两张图就并排展示：WebGL 与强制 Canvas 回落的差别要肉眼可判
        if ok and self._probe_tag:
            normal = self._shots_dir() / f"{self._probe_tag}-normal.png"
            canvas = self._shots_dir() / f"{self._probe_tag}-canvas.png"
            if normal.is_file() and canvas.is_file():
                _ProbeCompareDialog(normal, canvas, self).exec()
            self._probe_tag = ""

    def _need_project(self) -> str:
        path = self.edit_project.text().strip()
        if not path:
            self._append("[提示] 请先选择鸿蒙工程目录")
            return ""
        return path

    # ------------------------------------------------------------ 各操作

    def _run_build(self) -> None:
        project = self._need_project()
        if not project:
            return
        cfg = dep_mod.app_config.load()
        self._start(lambda on_line: toolchain_mod.build_project(project, on_line=on_line, cfg=cfg))

    def _run_install(self) -> None:
        hap = self.edit_hap.text().strip()
        if not hap:
            self._append("[提示] 没有 HAP：先编译，或用「浏览…」选一个")
            return
        cfg = dep_mod.app_config.load()
        bundle = self.edit_bundle.text().strip()
        self._start(lambda on_line: toolchain_mod.install_hap(hap, bundle, on_line=on_line, cfg=cfg))

    def _run_start(self) -> None:
        bundle = self.edit_bundle.text().strip()
        if not bundle:
            self._append("[提示] 请填 bundleName")
            return
        cfg = dep_mod.app_config.load()
        ability = self.edit_ability.text().strip() or "EntryAbility"
        self._start(lambda on_line: toolchain_mod.start_app(bundle, ability, on_line=on_line, cfg=cfg))

    def _run_snapshot(self) -> None:
        cfg = dep_mod.app_config.load()
        out = self._shots_dir() / "shot-manual.jpeg"
        self._start(lambda on_line: toolchain_mod.snapshot(out, on_line=on_line, cfg=cfg))

    def _run_inspect(self) -> None:
        hap = self.edit_hap.text().strip()
        bundle = self.edit_bundle.text().strip()
        if not hap:
            self._append("[提示] 巡检需要 HAP：先编译或手动选一个")
            return
        if not bundle:
            self._append("[提示] 巡检需要 bundleName（用于 aa start）")
            return
        taps = self._parse_taps()
        cfg = dep_mod.app_config.load()
        wait = float(self.spin_wait.value())
        shots = self._shots_dir()

        def task(on_line):
            return toolchain_mod.inspect(hap, bundle, wait_seconds=wait, shots_dir=shots,
                                         tag="inspect", taps=taps, cfg=cfg, on_line=on_line)
        self._start(task)

    def _run_probe(self) -> None:
        url = self.edit_url.text().strip()
        if not url:
            self._append("[提示] 请填探针页面 URL")
            return
        tag = time.strftime("%H%M%S")
        tag = f"probe-{tag}"
        shots = self._shots_dir()
        self._probe_tag = tag
        self._start(lambda on_line: toolchain_mod.probe_pair(
            url, shots, tag=tag, on_line=on_line))

    def _start_server(self) -> None:
        """把当前工程的 H5 资源目录起成本地 URL（相对路径资源必须走 http://）。"""
        root = self._guess_h5_root()
        if root is None:
            self._append("[提示] 没找到 H5 资源目录：请在左侧指定鸿蒙工程或用「浏览…」选一个含 index.html 的目录")
            return
        httpd, base, note = toolchain_mod.ensure_static_server(root)
        self._server = httpd
        if httpd is None:
            self._append("✗ " + note)
            return
        self._append("✓ " + note)
        self.edit_url.setText(base + "index.html")
        self._append(f"已填入探针 URL：{self.edit_url.text()}")

    def _guess_h5_root(self) -> Path | None:
        """找 index.html：鸿蒙工程的 rawfile / assets 优先，没有就退回工程根。"""
        roots: list[Path] = []
        project = self.edit_project.text().strip()
        if project:
            base = Path(project)
            roots += [base / "entry" / "src" / "main" / "resources" / "rawfile",
                      base / "entry" / "src" / "main" / "resources" / "resfile",
                      base]
        if self._session is not None:
            roots.append(self._session.project_dir / "assets")
            roots.append(self._session.work_dir)
        for root in roots:
            try:
                if root.is_dir() and (root / "index.html").is_file():
                    return root
            except OSError:
                continue
        return None

    def _parse_taps(self) -> list[tuple[int, int]]:
        taps: list[tuple[int, int]] = []
        raw = self.edit_taps.text().strip()
        if not raw:
            return taps
        for item in raw.replace("；", ";").split(";"):
            item = item.strip()
            if not item:
                continue
            try:
                x, y = (int(v) for v in item.replace("，", ",").split(","))
            except ValueError:
                self._append(f"[提示] 跳过非法坐标：{item}")
                continue
            taps.append((x, y))
        return taps

    def _shots_dir(self) -> Path:
        import wbox.config as app_config

        try:
            return app_config.workspace_sub(app_config.load(), "shots")
        except OSError:
            return Path.cwd() / "shots"

    # ------------------------------------------------------------ 产物

    def _open_artifact(self) -> None:
        if not self._last_artifact:
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl(Path(self._last_artifact).as_uri()))

    def _open_artifact_dir(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        target = Path(self._last_artifact) if self._last_artifact else None
        folder = target.parent if target is not None else self._shots_dir()
        QDesktopServices.openUrl(QUrl(folder.as_uri()))

    # ------------------------------------------------------------ 设备

    def _refresh_devices(self) -> None:
        if not self._hdc:
            self._append("[提示] 没有 hdc：先安装 HarmonyOS 命令行工具")
            return
        if self._dev_thread is not None and self._dev_thread.isRunning():
            return
        cfg = dep_mod.app_config.load()
        th = track_thread(_ListTargetsThread(cfg, self))
        th.log.connect(self._append)
        th.found.connect(self._on_devices)
        th.failed.connect(self._on_device_failed)
        self._dev_thread = th
        self._set_running(True)
        th.finished.connect(lambda: self._set_running(False))
        th.start()

    def _on_devices(self, lines: list) -> None:
        self.dev_list.clear()
        for text in lines:
            self.dev_list.addItem(str(text))
        self._device_count = len(lines)
        self.btn_open_artifact.setEnabled(bool(self._last_artifact))
        self._append(f"✓ 发现 {len(lines)} 台设备")
        self.refresh_env()

    def _on_device_failed(self, message: str) -> None:
        self.dev_list.clear()
        self._device_count = 0
        self._append("✗ " + str(message))
        self.refresh_env()

    # ------------------------------------------------------------ 收尾

    def wait_thread(self, msec: int = 5000) -> None:
        """等本页所有后台线程退出（主窗关闭 / 离屏冒烟收尾时调用）。"""
        for th in (self._thread, self._dev_thread):
            try:
                if th is not None and th.isRunning():
                    th.wait(msec)
            except RuntimeError:      # 底层 C++ 对象已销毁
                continue
        self._stop_server()

    def _stop_server(self) -> None:
        """关掉临时静态服务：留着会占端口，下次再起就抢不到首选端口。"""
        httpd = self._server
        self._server = None
        if httpd is None:
            return
        try:
            httpd.shutdown()        # type: ignore[attr-defined]
            httpd.server_close()    # type: ignore[attr-defined]
        except Exception:           # noqa: BLE001  服务已停也算 OK
            return

    @property
    def console_text(self) -> str:
        return self.console.toPlainText()
