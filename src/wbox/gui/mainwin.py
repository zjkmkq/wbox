"""wbox.gui.mainwin —— 主窗口：首页 ⇄ 工作区 ⇄ 三个独立页面。

结构（写死）：
  根 QStackedWidget: [首页 HomePage, 工作区 WorkspacePage, 形态诊断仪, 知识库, 排障台]
  工作区 = 顶部步骤导航 + QSplitter(左清单 | 中步骤栈 | 右记录) + 状态栏

首页是「路径选择器」：五张卡片各通一条旅程（一键流水线 / 五步专家模式 /
形态诊断仪 / 迁移知识库 / 排障台），不再是一排按钮或长列表。

遮挡治理（2026-10-27）：每个页面构建完都过 uikit.harden_window()，
主窗另设 setMinimumSize，保证窄窗口下内容可滚动而不是被裁掉。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from wbox import config as app_config
from wbox import deps as dep_mod
from wbox.ascii_names import non_ascii_parts, work_dir_name
from wbox.gui import steps as steps_pkg
from wbox.gui.settings import SettingsDialog
from wbox.gui.steps import pages as _steps_pages  # noqa: F401  触发六步注册
from wbox.gui.home import HomePage
from wbox.gui.pages import DoctorPage, KnowledgePage, TroubleshootPage
from wbox.gui.pages.tools import ToolsPage
from wbox.gui.panels.help import HelpCenterPanel
from wbox.gui.panels.inventory import InventoryPanel
from wbox.gui.session import ProjectSession
from wbox.gui.threads import track_thread, wait_all_threads
from wbox.gui.uikit import harden_window, install_text_guard

_PAGE_HOME = "home"
_PAGE_WORKSPACE = "workspace"
_PAGE_DOCTOR = "doctor"
_PAGE_KNOWLEDGE = "knowledge"
_PAGE_TROUBLESHOOT = "troubleshoot"
_PAGE_TOOLS = "tools"


class _DepProbeThread(QThread):
    """后台跑依赖检测，避免首次打开卡 UI。

    工作放 run() 里直接跑（不放事件循环）——run() 返回即线程结束。
    曾经的 moveToThread + started.connect(run) 写法有退出竞态：
    quit() 在 exec() 启动前调用会丢失，线程永不结束（离屏冒烟必现 127）。
    """
    done = Signal(list)

    def __init__(self, cfg: dict) -> None:
        super().__init__()
        self._cfg = cfg

    def run(self) -> None:
        try:
            self.done.emit(dep_mod.check_all(self._cfg))
        except Exception:  # noqa: BLE001
            self.done.emit([])


class _ShapeTagThread(QThread):
    """后台识别当前工程的形态，把标签喂给右栏「相关推荐」。

    只读扫描 work/ 目录（不解包、不写盘）；失败静默返回空标签——
    推荐列表少几条不打紧，绝不能让打开工程失败。
    """

    done = Signal(list)

    def __init__(self, work_dir: str) -> None:
        super().__init__()
        self._work_dir = work_dir

    def run(self) -> None:
        tags: list[str] = []
        try:
            from wbox import shape as shape_mod

            for match in shape_mod.detect_shape(self._work_dir)[:2]:
                for tag in (match.shape.get("tags") or []):
                    text = str(tag)
                    if text not in tags:
                        tags.append(text)
        except Exception:  # noqa: BLE001
            tags = []
        self.done.emit(tags)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("跨平台迁移白盒工作台 WBox")
        self.resize(1480, 920)
        self.setMinimumSize(1120, 700)   # 窗口再小也不能把内容裁掉
        self.cfg = app_config.load()
        self.session: ProjectSession | None = None
        # 全局防遮挡守卫：任何控件显示时就地加固其中的标签/表格（含运行时新建的）
        install_text_guard(QApplication.instance())

        root = QStackedWidget()
        self.setCentralWidget(root)
        self.root = root

        # ---- 首页（路径选择器）
        self.home = HomePage()
        self.home.open_project.connect(self.open_project)
        self.home.delete_recent.connect(self._on_delete_recent)
        self.home.new_project.connect(self.new_project)
        self.home.open_settings.connect(self.open_settings)
        self.home.use_lite_mode.connect(self.use_lite_mode)
        self.home.open_doctor.connect(lambda: self.show_page(_PAGE_DOCTOR))
        self.home.open_knowledge.connect(lambda: self.show_page(_PAGE_KNOWLEDGE))
        self.home.open_troubleshoot.connect(lambda: self.show_page(_PAGE_TROUBLESHOOT))
        root.addWidget(self.home)
        self._root_index: dict[str, int] = {_PAGE_HOME: 0}

        # ---- 工作区
        self.workspace = QWidget()
        self._root_index[_PAGE_WORKSPACE] = root.addWidget(self.workspace)
        self._build_workspace()

        # ---- 三个独立页面（各自带 ← 首页）
        self.doctor_page = DoctorPage()
        self.doctor_page.back.connect(self.go_home)
        self._root_index[_PAGE_DOCTOR] = root.addWidget(self.doctor_page)

        self.knowledge_page = KnowledgePage()
        self.knowledge_page.back.connect(self.go_home)
        self._root_index[_PAGE_KNOWLEDGE] = root.addWidget(self.knowledge_page)

        self.trouble_page = TroubleshootPage()
        self.trouble_page.back.connect(self.go_home)
        self.trouble_page.open_project.connect(self.open_project)
        self._root_index[_PAGE_TROUBLESHOOT] = root.addWidget(self.trouble_page)

        # 工具箱（编译/装机/启动/截图/巡检/探针）：从工作区顶栏进入，返回时回工作区
        self.tools_page = ToolsPage()
        self.tools_page.back.connect(self.back_to_workspace)
        self._root_index[_PAGE_TOOLS] = root.addWidget(self.tools_page)

        root.setCurrentIndex(0)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("就绪")
        self._refresh_home()
        harden_window(self)

    # ------------------------------------------------------------ 页面栈

    def show_page(self, name: str) -> None:
        idx = self._root_index.get(name)
        if idx is None:
            return
        if name == _PAGE_TROUBLESHOOT:
            self.trouble_page.reload_if_needed()   # 切到才读盘，不在启动时抢线程
        if name == _PAGE_TOOLS:
            self.tools_page.set_session(self.session)
        self.root.setCurrentIndex(idx)

    def back_to_workspace(self) -> None:
        """从工具箱返回：有会话回工作区，没有就回首页。"""
        name = _PAGE_WORKSPACE if self.session is not None else _PAGE_HOME
        self.root.setCurrentIndex(self._root_index[name])

    # ------------------------------------------------------------ 工作区骨架

    def _build_workspace(self) -> None:
        lay = QVBoxLayout(self.workspace)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # 顶部：返回 + 工程名 + 步骤导航 + 保存
        top = QHBoxLayout()
        top.setContentsMargins(10, 8, 10, 8)
        btn_home = QPushButton("← 首页")
        btn_home.clicked.connect(self.go_home)
        top.addWidget(btn_home)
        self.project_label = QLabel("（未打开工程）")
        self.project_label.setObjectName("h2")
        # 工程名/路径可能很长：给最小宽度 + 全文 tooltip，防被步骤按钮挤没
        self.project_label.setMinimumWidth(120)
        self.project_label.setToolTip("")
        top.addWidget(self.project_label)
        top.addStretch(1)

        self.step_buttons: dict[str, QPushButton] = {}
        for cls in steps_pkg.STEPS:
            btn = QPushButton(cls.title)
            btn.setObjectName("step")
            btn.setCheckable(True)
            # 按钮只放得下短标题；subtitle 全解进 tooltip（2026-10-25 遮挡修复）
            btn.setToolTip(f"{cls.title} —— {cls.subtitle}")
            btn.clicked.connect(lambda _checked=False, sid=cls.step_id: self.goto_step(sid))
            self.step_buttons[cls.step_id] = btn
            top.addWidget(btn)

        self.btn_tools = QPushButton("工具箱")
        self.btn_tools.setToolTip("编译工程 / 装机 / 启动 / 截图 / 一键巡检 / 浏览器探针")
        self.btn_tools.clicked.connect(lambda: self.show_page(_PAGE_TOOLS))
        top.addWidget(self.btn_tools)
        self.btn_save = QPushButton("保存")
        self.btn_save.setObjectName("primary")
        self.btn_save.clicked.connect(self.save_project)
        top.addWidget(self.btn_save)
        lay.addLayout(top)

        # 三栏
        split = QSplitter(Qt.Orientation.Horizontal)
        self.inventory = InventoryPanel()
        self.inventory.status_hint.connect(lambda msg: self.statusBar().showMessage(msg, 8000))
        self.step_stack = QStackedWidget()
        # 右栏：帮助中心（情境教程 / 搜索 / 推荐）+ 记录（降为 Tab）
        self.help = HelpCenterPanel(self.cfg)
        self.records = self.help.records      # 兼容既有调用点（records.refresh）
        split.addWidget(self.inventory)
        split.addWidget(self.step_stack)
        split.addWidget(self.help)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 6)
        split.setStretchFactor(2, 3)
        split.setCollapsible(0, False)
        split.setCollapsible(1, False)
        split.setCollapsible(2, False)
        lay.addWidget(split, stretch=1)

        self._pages: dict[str, QWidget] = {}

    # ------------------------------------------------------------ 首页交互

    def _refresh_home(self) -> None:
        self.home.set_recent(self.cfg.get("recent_projects", []))
        # 工作区路径 + 模式徽标 + 命名显示（2026-10-25 产品化）
        try:
            ws_root = str(app_config.workspace_root(self.cfg))
        except OSError:
            ws_root = "（工作区不可写，请在设置中更换）"
        self.home.set_workspace(ws_root, self.cfg.get("mode", "pro"))
        self.inventory.set_zh(self.cfg.get("naming_display", "zh") == "zh")
        # 后台跑依赖检测，回来只刷一句提示（列表在设置 → 插件与依赖）
        self.home.set_dep_loading()
        self._dep_thread = track_thread(_DepProbeThread(self.cfg))
        self._dep_thread.done.connect(self.home.refresh_deps)
        self._dep_thread.start()

    def _on_delete_recent(self, path: str) -> None:
        """从最近列表移除一项（不删工程本身），原子保存后立即刷新首页。"""
        self.cfg = app_config.remove_recent_project(self.cfg, path)
        app_config.save(self.cfg)
        self.home.set_recent(self.cfg.get("recent_projects", []))
        self.statusBar().showMessage("已从最近列表移除", 3000)

    def open_settings(self, page: str = "") -> None:
        """设置对话框：保存后刷新首页工作区/模式、清单命名显示、实时换肤。

        page: ""=常规页；"plugins"=插件与依赖页（首页依赖提示跳转用）。
        """
        dlg = SettingsDialog(self.cfg, self, page=page)
        if dlg.exec():
            self.cfg = app_config.load()   # SettingsDialog 内部已原子保存
            # 实时换肤：读新主题并应用；同时刷新三栏 + 全部步骤页，
            # 让表格/标签前景色（theme.C_X）随主题更新
            theme_name = self.cfg.get("ui", {}).get("theme", "dark")
            from wbox.gui.theme import apply_theme
            apply_theme(QApplication.instance(), theme_name)
            self.help.set_cfg(self.cfg)      # 联网开关变了，联网区域要立刻响应
            self._refresh_home()
            if self.session is not None:
                self.records.refresh(self.session)
                self.inventory.refresh(self.session)
                for page_widget in self._pages.values():
                    page_widget.on_enter()
            self.statusBar().showMessage(f"设置已保存（主题：{theme_name}）", 5000)

    def use_lite_mode(self) -> None:
        """一键流水线卡片：APK → HAP 全自动（pipeline 未完工，先明确反馈）。"""
        QMessageBox.information(
            self, "一键流水线（建设中）",
            "该入口的目标是「拖入 APK → 自动跑完六步 → 直接出 HAP」，\n"
            "目前自动化流水线还在建设，尚未开放（未实现），先不装作能用。\n\n"
            "现在可以走的两条路：\n"
            "  · 五步专家模式：每一步都能看见、能改、能回退；\n"
            "  · 形态诊断仪：先确认这包是什么形态、大概几步、有哪些坑。")
        # 记录用户选择，不切换 cfg（模式未建成，避免徽标说谎）
        self.cfg["mode"] = "pro"
        app_config.save(self.cfg)
        self._refresh_home()

    def go_home(self) -> None:
        if self.session and self.session.dirty:
            r = QMessageBox.question(self, "未保存的修改", "当前工程有未保存修改，保存吗？",
                                     QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                                     | QMessageBox.StandardButton.Cancel)
            if r == QMessageBox.StandardButton.Cancel:
                return
            if r == QMessageBox.StandardButton.Save:
                self.save_project()
        self.session = None
        self.root.setCurrentIndex(self._root_index[_PAGE_HOME])
        self._refresh_home()

    def new_project(self) -> None:
        apk, _ = QFileDialog.getOpenFileName(self, "选择 APK", "", "APK (*.apk)")
        if not apk:
            return
        # 默认存工作区 projects/（D 盘优先，设置里可改根目录，此处仍可临时改）
        try:
            default_dir = str(app_config.workspace_sub(self.cfg, "projects"))
        except OSError:
            default_dir = ""
        folder = QFileDialog.getExistingDirectory(self, "选择工程目录（新建工程的存放位置）", default_dir)
        if not folder:
            return
        # 工程目录名 ASCII 化（DevEco Studio 不识别中文目录，2026-10-25 铁律）：
        # 中文 APK 名 "92934圆锯模拟器8.apk" → 工程目录 "92934yjmnq8.wbox"（拼音首字母）
        target = Path(folder) / (work_dir_name(Path(apk).stem) + ".wbox")
        target.mkdir(parents=True, exist_ok=True)
        if non_ascii_parts(target):
            QMessageBox.warning(
                self, "目录含中文",
                f"存放目录 {folder} 含非 ASCII 字符。\n"
                f"DevEco Studio 无法识别中文目录，后续鸿蒙工程将输出到同级英文目录；"
                f"如无法编译，请把工程移到全英文路径（如 D:\\wbox\\）。")
        try:
            session = ProjectSession.create_new(target, apk)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "新建失败", str(e))
            return
        self._open_session(session, note="新工程已创建，请进入「① 拆」生成清单")
        self.goto_step("extract")

    def open_project(self, path: str) -> None:
        target = Path(path)
        if not (target / "spec.json").is_file():
            QMessageBox.warning(self, "无法打开", f"目录下没有 spec.json：{target}")
            return
        try:
            session = ProjectSession(target)
            session.load()
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "打开失败", str(e))
            return
        self._open_session(session)

    def _open_session(self, session: ProjectSession, note: str = "") -> None:
        self.session = session
        session.changed.connect(self._on_session_changed)
        self.cfg = app_config.touch_recent_project(self.cfg, session.project_dir, session.project_name)
        app_config.save(self.cfg)
        self.project_label.setText(session.project_name)
        self.project_label.setToolTip(str(session.project_dir))
        self.root.setCurrentIndex(self._root_index[_PAGE_WORKSPACE])
        self._rebuild_pages()
        self.inventory.refresh(session)
        self.records.refresh(session)
        self.tools_page.set_session(session)
        self._detect_shape_tags(session)
        self.goto_step(self.cfg.get("ui", {}).get("last_step", "extract"))
        self.statusBar().showMessage(note or f"已打开工程：{session.project_dir}")

    def _detect_shape_tags(self, session: ProjectSession) -> None:
        """后台跑一次形态识别，把标签交给帮助中心做相关推荐（可选增强）。"""
        work_dir = session.work_dir
        if not work_dir.is_dir():
            return
        th = track_thread(_ShapeTagThread(str(work_dir)))
        th.done.connect(self.help.set_tags)
        self._tag_thread = th
        th.start()

    def _on_session_changed(self, _note: str) -> None:
        """spec 变更后联动刷新左右栏（中栏各步自行刷新）。"""
        if self.session:
            self.inventory.refresh(self.session)
            self.records.refresh(self.session)

    # ------------------------------------------------------------ 步骤切换

    def _rebuild_pages(self) -> None:
        # 清空旧页
        while self.step_stack.count():
            w = self.step_stack.widget(0)
            self.step_stack.removeWidget(w)
            w.deleteLater()
        self._pages.clear()
        assert self.session is not None
        for cls in steps_pkg.STEPS:
            page = cls(self.session)
            page.navigate.connect(self.goto_step)
            self.step_stack.addWidget(page)
            self._pages[cls.step_id] = page

    def goto_step(self, step_id: str) -> None:
        page = self._pages.get(step_id)
        if page is None:
            return
        self.step_stack.setCurrentWidget(page)
        for sid, btn in self.step_buttons.items():
            btn.setChecked(sid == step_id)
        # 右栏帮助中心跟着当前步骤换"情境教程"
        self.help.set_step(step_id, getattr(page, "title", ""))
        self.cfg["ui"]["last_step"] = step_id
        app_config.save(self.cfg)
        page.on_enter()

    # ------------------------------------------------------------ 保存

    def save_project(self) -> None:
        if not self.session:
            return
        try:
            self.session.save("手动保存")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "保存失败", str(e))
            return
        self.inventory.refresh(self.session)
        self.records.refresh(self.session)
        self.statusBar().showMessage(f"已保存 {self.session.spec_path}")

    # ------------------------------------------------------------ 关闭确认

    def closeEvent(self, event) -> None:  # noqa: N802  Qt 命名
        if self.session and self.session.dirty:
            r = QMessageBox.question(self, "未保存的修改", "退出前保存吗？",
                                     QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                                     | QMessageBox.StandardButton.Cancel)
            if r == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if r == QMessageBox.StandardButton.Save:
                self.save_project()
        # 等所有后台线程退出，避免 QThread 销毁中运行（离屏冒烟退出码 127）
        self._wait_threads()
        event.accept()

    def _wait_threads(self) -> None:
        th = getattr(self, "_dep_thread", None)
        if th is not None and th.isRunning():
            th.quit()
            th.wait(3000)
        tag = getattr(self, "_tag_thread", None)
        if tag is not None and tag.isRunning():
            tag.wait(5000)
        self.help.wait_threads()
        self.tools_page.wait_thread()
        self.doctor_page.wait_thread()
        self.trouble_page.wait_thread()
        # 兜底：登记表里任何漏网线程都在这里收掉，宁可多等几秒也不要出 127
        wait_all_threads()
