"""wbox.gui.panels.help —— 右栏「帮助中心」：情境教程 + 本地/联网搜索 + 相关推荐。

存在理由（用户需求）：右栏原来只是"记录"，看完就没了；实际工作时更常问的是
"这一步我该注意什么"。所以把右栏升级成帮助中心，用三个区域回答三个问题：

  上：**我现在这一步该看哪篇** —— 按当前步骤从 src/wbox/tutorials/*.md 匹配
  中：**我要查的那个词在哪** —— 先查本地（教程全文 + 形态模板），查不到再联网
  下：**跟这件事相关的还有什么** —— 按步骤/标签打分推荐

离线策略（用户明确要求，写死）：
- 没网 → 整个联网区域不显示（不占位、不报错）；
- 有网但设置里关了 ui.online_help → 同样隐藏；
- 默认开。
"记录"面板不丢，降为本面板的第二个 Tab。

铁律：网络探测放 QThread 子类 run()；内嵌浏览器不可用时降级为系统浏览器，
原因写在界面上（见 webview.py）。
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from wbox import shape as shape_mod
from wbox import tutorial as tutorial_mod
from wbox.gui import theme
from wbox.gui.pages.knowledge import shape_markdown
from wbox.gui.panels.records import RecordsPanel
from wbox.gui.threads import track_thread
from wbox.gui.uikit import harden_window, plain_text, wrap_label
from wbox.gui.webview import OnlineSearchDialog, SEARCH_ENGINE_NAME, webengine_available

_KIND_TUTORIAL = "tutorial"
_KIND_SHAPE = "shape"


# ---------------------------------------------------------------- 教程阅读窗

class TutorialDialog(QDialog):
    """教程全文阅读窗（QTextBrowser.setMarkdown 渲染，可外部打开原文件）。"""

    def __init__(self, tut: tutorial_mod.Tutorial, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tut = tut
        self.setWindowTitle(f"教程 —— {tut.title}")
        self.resize(940, 720)
        self.setMinimumSize(560, 420)

        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        head = QLabel(tut.title)
        head.setObjectName("h1")
        lay.addWidget(head)
        meta = "　·　".join(x for x in (
            tut.summary,
            ("标签：" + "、".join(tut.tags)) if tut.tags else "",
            ("适用步骤：" + "、".join(tut.steps)) if tut.steps else "",
        ) if x)
        if meta:
            lay.addWidget(wrap_label(meta, object_name="muted"))

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setLineWrapMode(QTextBrowser.LineWrapMode.WidgetWidth)
        self.browser.setMarkdown(tut.body or "（这篇教程正文为空）")
        lay.addWidget(self.browser, stretch=1)

        bar = QHBoxLayout()
        bar.addStretch(1)
        if tut.path is not None:
            btn_file = QPushButton("打开源文件")
            btn_file.setToolTip(str(tut.path))
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices

            btn_file.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl(tut.path.as_uri())))
            bar.addWidget(btn_file)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        bar.addWidget(btn_close)
        lay.addLayout(bar)
        harden_window(self)


# ---------------------------------------------------------------- 网络探测

class _NetThread(QThread):
    """探测联网状态（3 秒超时，任一常用源可达即有网）。"""

    done = Signal(bool, str)

    def run(self) -> None:
        try:
            from wbox import plugins as plugins_mod

            online, note = plugins_mod.network_summary()
            self.done.emit(bool(online), str(note))
        except Exception:  # noqa: BLE001
            self.done.emit(False, "网络状态未知")


# ---------------------------------------------------------------- 帮助中心主体

class HelpCenterPanel(QTabWidget):
    """右栏主体：帮助中心 + 记录。"""

    def __init__(self, cfg: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.help_page = HelpCenterContent(cfg)
        self.records = RecordsPanel()
        self.addTab(self.help_page, "帮助")
        self.addTab(self.records, "记录")
        self.setMinimumWidth(320)
        harden_window(self)

    # ---- 转发给帮助页的便捷方法（主窗调用）

    def set_step(self, step_id: str, step_title: str = "") -> None:
        self.help_page.set_step(step_id, step_title)

    def set_cfg(self, cfg: dict) -> None:
        self.cfg = cfg
        self.help_page.set_cfg(cfg)

    def set_tags(self, tags: list[str]) -> None:
        self.help_page.set_tags(tags)

    def refresh(self, session=None) -> None:
        """兼容旧调用点（原来右栏只有 records.refresh(session)）。"""
        self.records.refresh(session) if session is not None else None

    def wait_threads(self, msec: int = 5000) -> None:
        self.help_page.wait_threads(msec)


class HelpCenterContent(QWidget):
    """帮助中心三区：情境教程 / 搜索 / 相关推荐。"""

    def __init__(self, cfg: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self._step = ""
        self._step_title = ""
        self._tags: list[str] = []
        self._net_thread: _NetThread | None = None
        self._net_probed = False
        self._online = False
        self._dialogs: list[QDialog] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        self.step_label = QLabel("当前步骤：—")
        self.step_label.setObjectName("muted")
        lay.addWidget(self.step_label)

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self._build_tutorial_box())
        split.addWidget(self._build_search_box())
        split.addWidget(self._build_related_box())
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 4)
        split.setStretchFactor(2, 3)
        for i in range(3):
            split.setCollapsible(i, False)
        lay.addWidget(split, stretch=1)

        self.reload_content()
        harden_window(self)

    # ------------------------------------------------------------ 区块

    def _build_tutorial_box(self) -> QWidget:
        box = QGroupBox("情境教程（跟着当前步骤走）")
        lay = QVBoxLayout(box)
        lay.setSpacing(4)
        self.tut_list = QListWidget()
        self.tut_list.setAlternatingRowColors(True)
        self.tut_list.itemDoubleClicked.connect(self._open_tutorial_item)
        lay.addWidget(self.tut_list, stretch=1)
        self.tut_hint = QLabel("")
        self.tut_hint.setObjectName("muted")
        lay.addWidget(self.tut_hint)
        return box

    def _build_search_box(self) -> QWidget:
        box = QGroupBox("搜索（先查本地，再问联网）")
        lay = QVBoxLayout(box)
        lay.setSpacing(4)

        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("教程 / 形态 关键词，回车搜索…")
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self._do_search)
        row.addWidget(self.search, stretch=1)
        btn = QPushButton("查")
        btn.setMaximumWidth(44)
        btn.clicked.connect(self._do_search)
        row.addWidget(btn)
        lay.addLayout(row)

        self.result_list = QListWidget()
        self.result_list.setAlternatingRowColors(True)
        self.result_list.itemDoubleClicked.connect(self._open_result_item)
        lay.addWidget(self.result_list, stretch=1)

        # 联网区域：默认整体隐藏；只有"本地无结果 + 有网 + 开关开着"才显示
        self.online_box = QWidget()
        online_lay = QVBoxLayout(self.online_box)
        online_lay.setContentsMargins(0, 0, 0, 0)
        online_lay.setSpacing(4)
        self.online_hint = QLabel("")
        self.online_hint.setObjectName("muted")
        online_lay.addWidget(self.online_hint)
        self.btn_online = QPushButton(f"联网搜索（{SEARCH_ENGINE_NAME}）")
        self.btn_online.clicked.connect(self._online_search)
        online_lay.addWidget(self.btn_online)
        self.online_box.setVisible(False)
        lay.addWidget(self.online_box)
        return box

    def _build_related_box(self) -> QWidget:
        box = QGroupBox("相关推荐")
        lay = QVBoxLayout(box)
        self.rel_list = QListWidget()
        self.rel_list.itemDoubleClicked.connect(self._open_tutorial_item)
        lay.addWidget(self.rel_list, stretch=1)
        return box

    # ------------------------------------------------------------ 数据

    def reload_content(self) -> None:
        """重新读取教程库（教程文件可能被用户改过）。"""
        self._fill_tutorials()
        self._fill_related()

    def set_step(self, step_id: str, step_title: str = "") -> None:
        self._step = (step_id or "").strip()
        self._step_title = step_title
        label = f"当前步骤：{step_title}" if step_title else f"当前步骤：{self._step or '—'}"
        self.step_label.setText(label)
        self.step_label.setToolTip(label)
        self._fill_tutorials()
        self._fill_related()

    def set_tags(self, tags: list[str]) -> None:
        self._tags = [t for t in (tags or []) if t]
        self._fill_related()

    def set_cfg(self, cfg: dict) -> None:
        self.cfg = cfg
        self._net_probed = False
        self._apply_online_visibility()

    def _fill_tutorials(self) -> None:
        self.tut_list.clear()
        items = tutorial_mod.by_step(self._step, limit=3) if self._step else \
            tutorial_mod.load_tutorials()[:3]
        for tut in items:
            item = QListWidgetItem(tut.title)
            item.setData(Qt.ItemDataRole.UserRole, (_KIND_TUTORIAL, tut.slug))
            item.setToolTip(plain_text("\n".join(
                x for x in (tut.title, tut.summary, "标签：" + "、".join(tut.tags)) if x)))
            self.tut_list.addItem(item)
        if not items:
            self.tut_hint.setText("教程目录为空（src/wbox/tutorials/），内容待补充")
        else:
            self.tut_hint.setText(f"{len(items)} 篇与本步骤相关　双击阅读")
        self.tut_hint.setToolTip(self.tut_hint.text())

    def _fill_related(self) -> None:
        self.rel_list.clear()
        exclude = set()
        for i in range(self.tut_list.count()):
            data = self.tut_list.item(i).data(Qt.ItemDataRole.UserRole)
            if data:
                exclude.add(data[1])
        items = tutorial_mod.related(self._tags, self._step, limit=6, exclude=exclude)
        if not items:                      # 兜底：给出最靠前的几篇，别留空列表
            items = [t for t in tutorial_mod.load_tutorials() if t.slug not in exclude][:6]
        for tut in items:
            item = QListWidgetItem(tut.title)
            item.setData(Qt.ItemDataRole.UserRole, (_KIND_TUTORIAL, tut.slug))
            item.setToolTip(plain_text(tut.summary or tut.title))
            self.rel_list.addItem(item)
        if not items:
            item = QListWidgetItem("（暂无推荐）")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.rel_list.addItem(item)

    # ------------------------------------------------------------ 搜索

    def _do_search(self) -> None:
        keyword = self.search.text().strip()
        self.result_list.clear()
        self.online_box.setVisible(False)
        if not keyword:
            return

        hits: list[tuple[str, str, str, str]] = []   # (显示文本, 标题, 摘要, kind:ref)
        for tut in tutorial_mod.search(keyword):
            hits.append((f"【教程】{tut.title}", tut.title, tut.summary, f"{_KIND_TUTORIAL}:{tut.slug}"))
        low = keyword.lower()
        for shp in shape_mod.load_shapes():
            hay = " ".join([
                str(shp.get("name") or ""), str(shp.get("summary") or ""),
                " ".join(str(t) for t in (shp.get("tags") or [])),
                shape_markdown(shp),
            ]).lower()
            if low in hay:
                hits.append((f"【形态】{shp.get('name', shp.get('shape_id', ''))}",
                             str(shp.get("name") or ""), str(shp.get("summary") or ""),
                             f"{_KIND_SHAPE}:{shp.get('shape_id', '')}"))

        for title, _t, summary, ref in hits:
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, ref)
            item.setToolTip(plain_text(summary or title))
            self.result_list.addItem(item)

        if hits:
            self.result_list.setCurrentRow(0)
            return
        # 本地无结果 → 决定是否露出联网区域
        empty = QListWidgetItem("本地知识库没找到相关内容")
        empty.setFlags(empty.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self.result_list.addItem(empty)
        self._maybe_offer_online(keyword)

    def _maybe_offer_online(self, keyword: str) -> None:
        """本地没命中时，只有"开关开着 + 确实有网"才显示联网按钮。"""
        if not bool((self.cfg.get("ui") or {}).get("online_help", True)):
            self.online_box.setVisible(False)
            return
        if not self._net_probed:
            self._probe_net()      # 探测完由回调决定是否显示
            self._pending_keyword = keyword
            return
        if not self._online:
            self.online_box.setVisible(False)
            return
        self.online_hint.setText(
            f"本地没有，可去 {SEARCH_ENGINE_NAME} 查「{keyword}」"
            + ("" if webengine_available() else "（本环境将用系统浏览器）"))
        self.online_hint.setToolTip(self.online_hint.text())
        self._pending_keyword = keyword
        self.online_box.setVisible(True)

    def _probe_net(self) -> None:
        if self._net_thread is not None and self._net_thread.isRunning():
            return
        th = track_thread(_NetThread(self))
        th.done.connect(self._on_net)
        self._net_thread = th
        th.start()

    def _on_net(self, online: bool, _note: str) -> None:
        self._net_probed = True
        self._online = online
        keyword = getattr(self, "_pending_keyword", "")
        if keyword:
            self._maybe_offer_online(keyword)

    def _online_search(self) -> None:
        keyword = getattr(self, "_pending_keyword", "") or self.search.text().strip()
        if not keyword:
            return
        dlg = OnlineSearchDialog(keyword, self)
        self._dialogs.append(dlg)
        dlg.finished.connect(lambda _r: self._dialogs.remove(dlg) if dlg in self._dialogs else None)
        dlg.show()          # 非模态：不阻塞主窗，也方便一边看一边操作

    def _apply_online_visibility(self) -> None:
        """设置里关掉联网 → 立刻收起联网区域（不占位）。"""
        if not bool((self.cfg.get("ui") or {}).get("online_help", True)):
            self.online_box.setVisible(False)

    # ------------------------------------------------------------ 打开条目

    def _open_tutorial_item(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, tuple) and data and data[0] == _KIND_TUTORIAL:
            self._open_tutorial(data[1])

    def _open_tutorial(self, slug: str) -> None:
        tut = tutorial_mod.get(slug)
        if tut is None:
            return
        dlg = TutorialDialog(tut, self)
        dlg.exec()

    def _open_result_item(self, item: QListWidgetItem) -> None:
        ref = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(ref, str) or ":" not in ref:
            return
        kind, _, ident = ref.partition(":")
        if kind == _KIND_TUTORIAL:
            self._open_tutorial(ident)
        elif kind == _KIND_SHAPE:
            shp = shape_mod.get_shape(ident)
            if shp is None:
                return
            dlg = QDialog(self)
            dlg.setWindowTitle(f"形态 —— {shp.get('name', ident)}")
            dlg.resize(900, 700)
            inner = QVBoxLayout(dlg)
            browser = QTextBrowser()
            browser.setOpenExternalLinks(True)
            browser.setMarkdown(shape_markdown(shp))
            inner.addWidget(browser, stretch=1)
            btn = QPushButton("关闭")
            btn.clicked.connect(dlg.accept)
            inner.addWidget(btn)
            harden_window(dlg)
            dlg.exec()

    # ------------------------------------------------------------ 收尾

    def wait_threads(self, msec: int = 5000) -> None:
        th = self._net_thread
        if th is not None and th.isRunning():
            th.wait(msec)
