"""wbox.gui.settings —— 设置对话框（2026-10-27 改版：分页 + 插件与依赖）。

覆盖用户运行部署要求：
- 存储路径优先 D 盘：工作区根目录（默认 D:/WBoxWork，可改、操作时可改）
- 任务完成后自动关机（默认关；确认后 shutdown /s /t 60，60s 内可取消）
- 避免删除：删除一律进工作区 .wtrash/，不物理 unlink
- 命名显示：文件系统恒英文；UI 层中文显示开关
- 使用层级：pro=专业开发者 / lite=普通用户（一键流水线）
- 帮助中心：ui.online_help 联网开关（关=不显示联网区域，无网=自动隐藏）
- 工具路径：java / apktool / command-line-tools（沿用既有 config.tools）

分页（2026-10-27）：常规 / 插件与依赖 / 高级。依赖体检整块从首页搬进
「插件与依赖」页（必需组缺失红标可一键安装，可选组按需装），首页只留一行提示。

铁律：插件页的检测/安装都在 QThread 里跑，对话框关闭前 wait_threads()，
绝不让后台线程活着——离屏冒烟会挂在退出码 127。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from wbox import config as app_config
from wbox.gui.panels.plugins import PluginsPage
from wbox.gui.theme import THEME_LABELS, THEME_NAMES
from wbox.gui.uikit import harden_window, wrap_label


class SettingsDialog(QDialog):
    def __init__(self, cfg: dict, parent=None, page: str = "") -> None:
        super().__init__(parent)
        self.cfg = json.loads(json.dumps(cfg))  # 深拷贝，取消不改原配置
        self.setWindowTitle("设置")
        self.resize(760, 640)
        self.setMinimumSize(640, 520)
        lay = QVBoxLayout(self)

        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, stretch=1)
        self.tabs.addTab(self._build_general(), "常规")
        self.plugins_page = PluginsPage(self.cfg)
        self.plugins_page.log.connect(lambda msg: self.hint_label.setText(msg))
        self.tabs.addTab(self.plugins_page, "插件与依赖")
        self.tabs.addTab(self._build_advanced(), "高级")
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # 底部提示行：插件安装进度/结论有地方说，不再靠弹窗堆
        self.hint_label = QLabel("")
        self.hint_label.setObjectName("muted")
        lay.addWidget(self.hint_label)

        # ---------------- 按钮 ----------------
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply)
        buttons.accepted.connect(self._apply_and_accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply_only)
        lay.addWidget(buttons)

        if page == "plugins":
            self.tabs.setCurrentWidget(self.plugins_page)
        harden_window(self)

    # ------------------------------------------------------------ 常规页

    def _build_general(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(12)

        gb_mode = QGroupBox("使用层级")
        fm_mode = QFormLayout(gb_mode)
        self.combo_mode = QComboBox()
        self.combo_mode.addItem("专业开发者（六步白盒工作台：拆→画→判→填→装配→缝）", "pro")
        self.combo_mode.addItem("普通用户（一键流水线：APK → HAP，AI 全流程）", "lite")
        cur_mode = str(self.cfg.get("mode", "pro"))
        idx = self.combo_mode.findData(cur_mode)
        if idx >= 0:
            self.combo_mode.setCurrentIndex(idx)
        fm_mode.addRow("模式：", self.combo_mode)
        lay.addWidget(gb_mode)

        gb_appearance = QGroupBox("外观与帮助")
        fm_appearance = QFormLayout(gb_appearance)
        self.combo_theme = QComboBox()
        for tname in THEME_NAMES:
            self.combo_theme.addItem(THEME_LABELS.get(tname, tname), tname)
        cur_theme = str(self.cfg.get("ui", {}).get("theme", "dark"))
        idx = self.combo_theme.findData(cur_theme)
        if idx >= 0:
            self.combo_theme.setCurrentIndex(idx)
        fm_appearance.addRow("主题：", self.combo_theme)
        fm_appearance.addRow("", wrap_label(
            "深色为 IDE 风格；浅色为最初经典白。修改后立即生效，可随时切回。",
            object_name="muted"))

        self.chk_online_help = QCheckBox("帮助中心启用联网搜索（本地知识库没结果时，联网查 Bing）")
        self.chk_online_help.setChecked(
            bool(self.cfg.get("ui", {}).get("online_help", True)))
        self.chk_online_help.setToolTip(
            "关闭后帮助中心只查本地教程与形态模板；未联网时该区域自动隐藏，不占位也不报错。")
        fm_appearance.addRow("", self.chk_online_help)
        lay.addWidget(gb_appearance)

        gb_ws = QGroupBox("工作区（所有产物集中存放，默认 D 盘）")
        fm_ws = QFormLayout(gb_ws)
        row_ws = QHBoxLayout()
        self.edit_ws = QLineEdit()
        self.edit_ws.setText(str(self.cfg.get("workspace", {}).get("root", "")))
        self.edit_ws.setPlaceholderText(f"默认：{app_config.default_workspace_root()}")
        btn_ws = QPushButton("浏览…")
        btn_ws.clicked.connect(self._pick_ws)
        row_ws.addWidget(self.edit_ws, stretch=1)
        row_ws.addWidget(btn_ws)
        fm_ws.addRow("工作区根目录：", row_ws)
        fm_ws.addRow("", wrap_label(
            "子目录规范：projects/ 迁移工程 · downloads/ 可下载资源 · "
            "special/ 特殊资源（so/字体等） · .wtrash/ 软删除回收区", object_name="muted"))
        lay.addWidget(gb_ws)

        gb_run = QGroupBox("运行与部署")
        fm_run = QFormLayout(gb_run)
        self.chk_shutdown = QCheckBox("任务完成后自动关机")
        self.chk_shutdown.setChecked(bool(self.cfg.get("behavior", {}).get("shutdown_on_finish", False)))
        fm_run.addRow("", self.chk_shutdown)
        self.chk_avoid_delete = QCheckBox("避免删除文件（删除移入 .wtrash/ 回收区，不物理删除）")
        self.chk_avoid_delete.setChecked(bool(self.cfg.get("behavior", {}).get("avoid_delete", True)))
        fm_run.addRow("", self.chk_avoid_delete)
        lay.addWidget(gb_run)

        gb_name = QGroupBox("文件命名显示")
        fm_name = QFormLayout(gb_name)
        self.combo_naming = QComboBox()
        self.combo_naming.addItem("中文显示（文件系统仍为英文名，AI 解析不受影响）", "zh")
        self.combo_naming.addItem("英文原文显示", "en")
        cur_naming = str(self.cfg.get("naming_display", "zh"))
        idx = self.combo_naming.findData(cur_naming)
        if idx >= 0:
            self.combo_naming.setCurrentIndex(idx)
        fm_name.addRow("界面显示：", self.combo_naming)
        lay.addWidget(gb_name)

        lay.addStretch(1)
        return page

    # ------------------------------------------------------------ 高级页

    def _build_advanced(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(12)

        gb_tools = QGroupBox("工具路径（留空=自动检测）")
        fm_tools = QFormLayout(gb_tools)
        tools = self.cfg.get("tools", {})
        self.edit_java = QLineEdit(str(tools.get("java_home", "")))
        self.edit_apktool = QLineEdit(str(tools.get("apktool_jar", "")))
        self.edit_clt = QLineEdit(str(tools.get("command_line_tools", "")))
        for edit, label, is_dir, placeholder in (
            (self.edit_java, "Java：", True, "JDK 根目录（含 bin/java.exe）"),
            (self.edit_apktool, "apktool：", False, "apktool.jar 路径"),
            (self.edit_clt, "SDK：", True, "HarmonyOS 命令行工具解压目录"),
        ):
            edit.setPlaceholderText(placeholder)
            row = QHBoxLayout()
            row.addWidget(edit, stretch=1)
            btn = QPushButton("浏览…")
            btn.clicked.connect(lambda _c=False, e=edit, d=is_dir: self._pick_tool(e, d))
            row.addWidget(btn)
            fm_tools.addRow(label, row)
        fm_tools.addRow("", wrap_label(
            "自动检测顺序：配置路径 → 应用内置工具目录 → 本机 DevEco Studio / PATH。",
            object_name="muted"))
        lay.addWidget(gb_tools)
        lay.addStretch(1)
        return page

    # ------------------------------------------------------------ 事件

    def _on_tab_changed(self, index: int) -> None:
        if self.tabs.widget(index) is self.plugins_page:
            self.plugins_page.refresh_if_needed()

    def showEvent(self, event) -> None:  # noqa: N802  Qt 命名
        super().showEvent(event)
        if self.tabs.currentWidget() is self.plugins_page:
            self.plugins_page.refresh_if_needed()

    def closeEvent(self, event) -> None:  # noqa: N802  Qt 命名
        # 后台线程必须在窗口销毁前收干净，否则解释器退出时挂在子进程上（退出码 127）
        self.plugins_page.wait_threads()
        super().closeEvent(event)

    def done(self, result: int) -> None:  # noqa: D102  Qt 命名
        # 确定/取消两条退出路径都要收线程（accept 走 done，不经过 closeEvent）
        self.plugins_page.wait_threads()
        super().done(result)

    def refresh_plugins(self) -> None:
        """供离屏脚本显式触发检测（不做自动，避免一构造就 spawn 子进程）。"""
        self.plugins_page.refresh()

    def _pick_ws(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择工作区根目录")
        if d:
            self.edit_ws.setText(d)

    def _pick_tool(self, edit: QLineEdit, is_dir: bool) -> None:
        if is_dir:
            d = QFileDialog.getExistingDirectory(self, "选择目录")
            if d:
                edit.setText(d)
        else:
            path, _ = QFileDialog.getOpenFileName(self, "选择文件")
            if path:
                edit.setText(path)

    def _collect(self) -> dict:
        cfg = self.cfg
        cfg["mode"] = str(self.combo_mode.currentData())
        ui = cfg.setdefault("ui", {})
        ui["theme"] = str(self.combo_theme.currentData())
        ui["theme_chosen"] = True  # 用户在设置里显式选过主题，后续尊重该选择
        ui["online_help"] = bool(self.chk_online_help.isChecked())
        ws = cfg.setdefault("workspace", {})
        ws["root"] = self.edit_ws.text().strip()
        behavior = cfg.setdefault("behavior", {})
        behavior["shutdown_on_finish"] = self.chk_shutdown.isChecked()
        behavior["avoid_delete"] = self.chk_avoid_delete.isChecked()
        cfg["naming_display"] = str(self.combo_naming.currentData())
        tools = cfg.setdefault("tools", {})
        tools["java_home"] = self.edit_java.text().strip()
        tools["apktool_jar"] = self.edit_apktool.text().strip()
        tools["command_line_tools"] = self.edit_clt.text().strip()
        return cfg

    def _apply_only(self) -> None:
        app_config.save(self._collect())
        self.plugins_page.set_cfg(self.cfg)
        QMessageBox.information(self, "已保存", "设置已保存。")

    def _apply_and_accept(self) -> None:
        app_config.save(self._collect())
        self.accept()


def maybe_shutdown_on_finish(cfg: dict, parent=None) -> None:
    """任务完成且设置开启自动关机时：倒计时关机（可取消）。

    shutdown /s /t 60 —— 60 秒倒计时；取消执行 shutdown /a。
    有可见父窗口时弹窗阻塞直到用户选择（立即关机=shutdown /s /t 0，
    取消=shutdown /a）；无界面（后台流水线/离屏测试）时只排队不弹窗，
    到时由系统自行关机。
    """
    if not bool((cfg.get("behavior") or {}).get("shutdown_on_finish", False)):
        return
    try:
        subprocess.Popen(["shutdown", "/s", "/t", "60"],
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        return
    if parent is None or not parent.isVisible():
        return
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("任务完成")
    box.setText("所有任务已完成。\n\n系统将在 60 秒后自动关机。")
    box.setInformativeText("点击「立即关机」马上执行；点击「取消」中止关机。")
    btn_now = box.addButton("立即关机", QMessageBox.ButtonRole.AcceptRole)
    btn_cancel = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    clicked = box.clickedButton()
    if clicked is btn_now:
        try:
            subprocess.Popen(["shutdown", "/s", "/t", "0"],
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError:
            pass
    else:
        try:
            subprocess.Popen(["shutdown", "/a"],
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError:
            pass
