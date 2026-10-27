"""wbox.gui.panels.plugins —— 设置 →「插件与依赖」页。

存在理由：依赖体检原本整块堆在首页，既占首屏又说不清"哪些必须装、哪些按需装"。
按用户要求搬进设置，并拆成两组：

  - 必需组：Java / apktool / jadx / HarmonyOS SDK / hvigor —— 缺一样主线就跑不动，
            缺失红字标记 + 一键安装（复用 wbox.plugins.install）。
  - 可选组：Pillow / fonttools / hdc / aapt2 —— 按需勾选安装，不装不影响主线。

铁律：
1. 检测与安装都放 QThread 子类（工作放 run()），禁止 moveToThread + quit() 那套
   会丢 quit 的写法——离屏冒烟会挂在 127。
2. 未实现自动安装的条目（aapt2 / hdc）按钮置灰并明写"未实现"，不许装作能用。
3. 离线时安装按钮置灰 + 顶部明说"未联网"，不让用户点了才失败。
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from wbox import plugins as plugins_mod
from wbox.gui import theme
from wbox.gui.threads import track_thread
from wbox.gui.uikit import configure_table, harden_window, plain_text

_COLUMNS = ["条目", "用途", "版本", "状态", "体积", "操作"]
_COL_STRETCH = {1}          # 用途列吃剩余宽度
_COL_NAME = 0
_COL_VERSION = 2
_COL_STATUS = 3
_COL_SIZE = 4
_COL_ACTION = 5

_STATUS_COLOR = {
    "已就绪": "C_SUCCESS_TXT",
    "缺失": "C_DANGER_TXT",
    "未安装": "C_FG_MUTED",
}


class _CatalogThread(QThread):
    """后台检测目录（会 spawn java/apktool 子进程，绝不能放 UI 线程）。"""

    done = Signal(list)
    net = Signal(bool, str)

    def __init__(self, cfg: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg

    def run(self) -> None:
        online, note = plugins_mod.network_summary()
        self.net.emit(online, note)
        try:
            self.done.emit([it.as_dict() for it in plugins_mod.catalog(self._cfg)])
        except Exception:  # noqa: BLE001
            self.done.emit([])


class _InstallThread(QThread):
    """后台安装：进度走信号（跨线程自动排队，不直接碰控件）。"""

    progressed = Signal(int, int)
    finished = Signal(str, bool, str)

    def __init__(self, pid: str, cfg: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pid = pid
        self._cfg = cfg

    def run(self) -> None:
        def cb(done: int, total: int) -> None:
            self.progressed.emit(done, total)
        try:
            r = plugins_mod.install(self._pid, progress=cb, cfg=self._cfg)
            self.finished.emit(self._pid, r.ok, (r.location if r.ok else r.message))
        except Exception as e:  # noqa: BLE001
            self.finished.emit(self._pid, False, f"安装过程出错：{e}")


class PluginsPage(QWidget):
    """插件与依赖页本体。构造不跑任何子进程（防离屏冒烟挂线程）。"""

    log = Signal(str)

    def __init__(self, cfg: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self._items: list[dict] = []
        self._online = False
        self._refreshed = False
        self._threads: list[QThread] = []
        self._install_thread: _InstallThread | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        # 顶部：网络状态 + 操作
        head = QHBoxLayout()
        self.net_label = QLabel("网络状态未检测")
        self.net_label.setObjectName("muted")
        head.addWidget(self.net_label, stretch=1)
        self.btn_recover = QPushButton("重新检测")
        self.btn_recover.clicked.connect(self.refresh)
        self.btn_install_all = QPushButton("安装全部缺失必需项")
        self.btn_install_all.setObjectName("primary")
        self.btn_install_all.setToolTip("按 Java → apktool → jadx → SDK 顺序依次安装缺失的必需项")
        self.btn_install_all.clicked.connect(self._install_all_required)
        head.addWidget(self.btn_install_all)
        head.addWidget(self.btn_recover)
        lay.addLayout(head)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setTextVisible(True)
        lay.addWidget(self.progress)

        # 必需组
        self.gb_required = QGroupBox("必需组件（缺一样，迁移主线就跑不动）")
        lay_req = QVBoxLayout(self.gb_required)
        self.req_hint = QLabel("尚未检测：点右上角「重新检测」查看本机状态")
        self.req_hint.setObjectName("muted")
        lay_req.addWidget(self.req_hint)
        self.table_required = self._make_table()
        lay_req.addWidget(self.table_required, stretch=1)
        lay.addWidget(self.gb_required, stretch=3)

        # 可选组
        self.gb_optional = QGroupBox("可选组件（按需安装，不装不影响主线）")
        lay_opt = QVBoxLayout(self.gb_optional)
        self.opt_hint = QLabel("增强功能：图片批处理 / 字体子集化 / 真机调试 / APK 资源表分析")
        self.opt_hint.setObjectName("muted")
        lay_opt.addWidget(self.opt_hint)
        self.table_optional = self._make_table()
        lay_opt.addWidget(self.table_optional, stretch=1)
        lay.addWidget(self.gb_optional, stretch=2)

        harden_window(self)

    # ------------------------------------------------------------ 表格

    def _make_table(self) -> QTableWidget:
        table = QTableWidget(0, len(_COLUMNS))
        configure_table(table, _COLUMNS, stretch_cols=_COL_STRETCH)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        return table

    def _fill(self, table: QTableWidget, items: list[dict]) -> None:
        table.setRowCount(len(items))
        for row, it in enumerate(items):
            status = "已就绪" if it.get("ok") else ("缺失" if it.get("required") else "未安装")
            vals = [
                str(it.get("name", "")),
                str(it.get("purpose", "")),
                str(it.get("version") or it.get("location") or "—"),
                status,
                _size_text(float(it.get("size_mb") or 0.0)),
            ]
            for c, text in enumerate(vals):
                item = QTableWidgetItem(text)
                item.setToolTip(plain_text(text))
                if c == _COL_STATUS:
                    from PySide6.QtGui import QColor

                    item.setForeground(QColor(getattr(theme, _STATUS_COLOR.get(status, "C_FG"))))
                if c == _COL_VERSION and it.get("detail"):
                    item.setToolTip(f"{text}\n{it.get('detail')}")
                table.setItem(row, c, item)
            table.setCellWidget(row, _COL_ACTION, self._action_widget(it))
            table.setItem(row, _COL_ACTION, QTableWidgetItem(""))
        table.resizeRowsToContents()

    def _action_widget(self, it: dict) -> QWidget:
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(4)
        pid = str(it.get("id", ""))
        if it.get("ok"):
            btn = QPushButton("已安装")
            btn.setEnabled(False)
            btn.setToolTip(str(it.get("location") or ""))
            lay.addWidget(btn)
            return wrap
        if not it.get("installable"):
            btn = QPushButton("不支持自动安装")
            btn.setEnabled(False)
            btn.setToolTip(str(it.get("install_note") or "未实现自动安装"))
            lay.addWidget(btn)
            lay.addWidget(self._link_button(it))
            return wrap
        btn = QPushButton("安装")
        btn.setObjectName("primary")
        if not self._online:
            btn.setEnabled(False)
            btn.setToolTip("未联网：连网后可用")
        else:
            btn.setToolTip(f"联网安装（约 {_size_text(float(it.get('size_mb') or 0.0))}）")
        btn.clicked.connect(lambda _checked=False, p=pid: self._install(p))
        lay.addWidget(btn)
        if it.get("homepage"):
            lay.addWidget(self._link_button(it))
        return wrap

    def _link_button(self, it: dict) -> QWidget:
        btn = QPushButton("官网")
        btn.setMaximumWidth(52)
        btn.setToolTip(f"在系统浏览器打开：{it.get('homepage')}")
        btn.clicked.connect(lambda _checked=False, u=str(it.get("homepage") or ""): self._open_url(u))
        return btn

    @staticmethod
    def _open_url(url: str) -> None:
        if not url:
            return
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        QDesktopServices.openUrl(QUrl(url))

    # ------------------------------------------------------------ 刷新

    def set_cfg(self, cfg: dict) -> None:
        self.cfg = cfg

    def refresh(self) -> None:
        """启动后台检测（幂等：已在跑就忽略）。"""
        for th in list(self._threads):
            if th.isRunning():
                return
        self.net_label.setText("正在检测网络与本机依赖…")
        self.btn_recover.setEnabled(False)
        th = track_thread(_CatalogThread(self.cfg))
        th.net.connect(self._on_net)
        th.done.connect(self._on_catalog)
        th.finished.connect(lambda: self._threads.remove(th) if th in self._threads else None)
        self._threads.append(th)
        th.start()

    def refresh_if_needed(self) -> None:
        """首次可见才检测：避免对话框一构造就 spawn 子进程。"""
        if not self._refreshed:
            self.refresh()

    def _on_net(self, online: bool, note: str) -> None:
        self._online = online
        self.net_label.setText(note)
        self.net_label.setToolTip(note)
        if not online:
            self.net_label.setStyleSheet(f"color: {theme.C_WARNING_TXT};")
            self.btn_install_all.setEnabled(False)
            self.btn_install_all.setToolTip("未联网：无法安装")
        else:
            self.net_label.setStyleSheet("")
            self.btn_install_all.setEnabled(True)
            self.btn_install_all.setToolTip("依次安装所有缺失的必需组件")

    def _on_catalog(self, items: list[dict]) -> None:
        self._refreshed = True
        self._items = items
        self.btn_recover.setEnabled(True)
        required = [i for i in items if i.get("required")]
        optional = [i for i in items if not i.get("required")]
        self._fill(self.table_required, required)
        self._fill(self.table_optional, optional)
        missing = [i.get("name", "") for i in required if not i.get("ok")]
        if missing:
            self.req_hint.setText(f"缺失 {len(missing)} 项：{'、'.join(missing)}")
            self.req_hint.setStyleSheet(f"color: {theme.C_DANGER_TXT};")
        else:
            self.req_hint.setText("全部必需组件已就绪")
            self.req_hint.setStyleSheet(f"color: {theme.C_SUCCESS_TXT};")
        self.req_hint.setToolTip(self.req_hint.text())
        self.btn_install_all.setEnabled(bool(missing) and self._online)
        self.log.emit(f"依赖检测完成：缺失 {len(missing)} 项必需组件")

    # ------------------------------------------------------------ 安装

    def _confirm_big(self, pid: str) -> bool:
        """大件（≥1GB）先确认，避免误点。"""
        it = next((i for i in self._items if i.get("id") == pid), None)
        size = float((it or {}).get("size_mb") or 0.0)
        if size < 1024:
            return True
        from PySide6.QtWidgets import QMessageBox

        r = QMessageBox.question(
            self, "确认下载",
            f"{(it or {}).get('name', pid)} 约 {size / 1024:.1f} GB，将从官方源下载并解压到本机工具目录。\n"
            f"耗时取决于网络，期间请勿关闭窗口。继续？")
        return r == QMessageBox.StandardButton.Yes

    def _install(self, pid: str) -> None:
        if self._install_thread is not None and self._install_thread.isRunning():
            self.log.emit("已有安装任务在进行，请等它结束")
            return
        if not self._confirm_big(pid):
            return
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)   # 不确定进度（下载前拿不到总长）
        self.progress.setFormat("准备中…")
        self.log.emit(f"开始安装：{pid}")
        th = track_thread(_InstallThread(pid, self.cfg))
        th.progressed.connect(self._on_progress)
        th.finished.connect(self._on_install_done)
        self._install_thread = th
        th.start()

    def _install_all_required(self) -> None:
        missing = [i.get("id") for i in self._items if i.get("required") and not i.get("ok")]
        if not missing:
            self.log.emit("必需组件已全部就绪")
            return
        self._queue = list(missing)
        self._install_one_by_one()

    def _install_one_by_one(self) -> None:
        queue = getattr(self, "_queue", [])
        if not queue:
            self.refresh()
            return
        pid = str(queue.pop(0))
        self._pending_then = queue
        it = next((i for i in self._items if i.get("id") == pid), None)
        if it is None or not it.get("installable"):
            self._install_one_by_one()
            return
        if not self._confirm_big(pid):
            self._queue = []
            return
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.progress.setFormat(f"安装中：{it.get('name', pid)}")
        th = track_thread(_InstallThread(pid, self.cfg))
        th.progressed.connect(self._on_progress)
        th.finished.connect(self._on_install_batch_done)
        self._install_thread = th
        th.start()

    def _on_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.progress.setRange(0, 100)
            self.progress.setValue(min(100, done * 100 // total))
            self.progress.setFormat(f"下载中 {done * 100 // total}%（{done / 1048576:.0f}/{total / 1048576:.0f} MB）")
        else:
            self.progress.setRange(0, 0)
            self.progress.setFormat("处理中…")

    def _on_install_done(self, pid: str, ok: bool, message: str) -> None:
        self.progress.setVisible(False)
        self.log.emit(("安装完成：" if ok else "安装失败：") + message)
        from PySide6.QtWidgets import QMessageBox

        if ok:
            QMessageBox.information(self, "安装完成", f"{pid} 已就绪：\n{message}")
        else:
            QMessageBox.warning(self, "安装失败", f"{pid}：\n{message}")
        self.refresh()

    def _on_install_batch_done(self, pid: str, ok: bool, message: str) -> None:
        self.progress.setVisible(False)
        self.log.emit(f"{pid}：{'成功' if ok else '失败'} — {message}")
        if not ok:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, "安装中断", f"{pid} 安装失败：\n{message}\n\n后续项已停止。")
            self._queue = []
            return
        self._install_one_by_one()

    # ------------------------------------------------------------ 收尾

    def wait_threads(self, msec: int = 5000) -> None:
        """等待后台线程结束（对话框关闭/离屏脚本退出前调用，防 127）。"""
        for th in list(self._threads):
            if th.isRunning():
                th.wait(msec)
        th = self._install_thread
        if th is not None and th.isRunning():
            th.wait(msec)


def _size_text(mb: float) -> str:
    if mb <= 0:
        return "—"
    if mb >= 1024:
        return f"{mb / 1024:.1f} GB"
    return f"{mb:.0f} MB"


def app_instance():
    """供离屏脚本取 QApplication（避免顶层 import 副作用）。"""
    return QApplication.instance()
