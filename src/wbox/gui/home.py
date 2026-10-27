"""wbox.gui.home —— 首页：五条路径的入口选择器。

定位（2026-10-27 改版）：首页不再是"长列表 + 依赖体检墙"，而是一个**路径选择器**——
五张卡片各自对应一条用户旅程，点进去就是那件事：

  ① 一键流水线    拖入 APK → 输出 HAP（自动化流水线建设中，卡片明确标注"建设中"，不装作能用）
  ② 五步专家模式  进现有工作区（拆→画→判→填→装配→缝）
  ③ 形态诊断仪    只丢 APK，出"这是什么形态 / 能不能迁 / 大概几步 / 有哪些坑"
  ④ 迁移知识库    浏览形态模板与迁移教程
  ⑤ 排障台        汇总所有工程的缝清单、失败案例与日志检索

依赖体检整块搬进设置 →「插件与依赖」；首页只留一条轻量提示（N 项缺失 → 去安装）。
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from wbox import spec as spec_mod
from wbox.gui import theme
from wbox.gui.uikit import harden_window, plain_text

# 卡片定义：(序号, 标题, 说明, 状态标记)
# 状态为空 = 可用；"建设中" = 未实现，卡片依然可点（点了会被告知现状）。
_PATHS: list[tuple[str, str, str, str]] = [
    ("①", "一键流水线",
     "拖入 APK，自动跑完拆→画→判→填→装配→缝，直接输出 HAP。适合不想逐步操作的使用者。",
     "建设中"),
    ("②", "五步专家模式",
     "进入白盒工作台：每一步都能看见、能改、能回退。适合要掌控迁移细节的开发者。",
     ""),
    ("③", "形态诊断仪",
     "只丢一个 APK 进来，先回答「这是什么形态、能不能迁、大概几步、有哪些坑」，再决定要不要动手。",
     ""),
    ("④", "迁移知识库",
     "按形态浏览迁移模板与教程：容器壳、原生引擎、WebView 远程包……每类都有步骤与验收清单。",
     ""),
    ("⑤", "排障台",
     "汇总所有工程的缝（seams）、失败案例与构建日志，支持全文检索定位历史问题。",
     ""),
]

# 最近工程状态徽标：状态文本 → QSS objectName（与 theme.py 里的 badge 样式对应）
_STATUS_BADGE: dict[str, str] = {
    "已完成": "badge-ok",     # 绿：编译已验证且无待补缝
    "进行中": "badge-warn",   # 橙：已动手但未编译验证
    "未开始": "badge",        # 青：仅拆包
    "—": "muted",            # 灰：无法读取 / 校验失败
}


def _derive_status(spec_path: Path) -> str:
    """从 spec.json 推导工程完成度（只读，不写盘）。

    性能：首页可能列出最多 10 个工程，每个都跑完整 jsonschema 校验会卡 UI
    （实测 1.7MB 的 spec 校验 ~360ms）。故常态走轻量 json.loads 直接读
    build_log/seams；仅当 spec_version 不符（需迁移）才走正式 spec.load。
    """
    if not spec_path.is_file():
        return "未开始"
    try:
        raw = json.loads(spec_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001  读不到 / 不是合法 JSON
        return "—"
    if raw.get("spec_version") != spec_mod.SPEC_VERSION:
        try:
            raw = spec_mod.load(spec_path)   # 偶尔的旧版本：正式迁移 + 校验
        except Exception:  # noqa: BLE001
            return "—"
    build_log = raw.get("build_log") or []
    actions = {b.get("action") for b in build_log if isinstance(b, dict)}
    seams = raw.get("seams") or []
    open_seams = any((s.get("status") == "open") for s in seams if isinstance(s, dict))
    if "compile_verified" in actions and not open_seams:
        return "已完成"
    if actions:
        return "进行中"
    return "未开始"


class _RecentRow(QWidget):
    """最近工程的一行：名称（粗体）+ 路径（次要、自动省略）+ 状态徽标 + 删除按钮。

    删除只从「最近列表」移除，不碰工程目录本身（avoid_delete 精神）。
    """

    def __init__(self, name: str, path: str, status: str,
                 on_delete, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._name = name
        self._path = path
        self.setMinimumHeight(54)
        self.setMaximumHeight(54)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(12)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)
        self.name_lbl = QLabel(name)
        self.name_lbl.setObjectName("h2")
        self.name_lbl.setToolTip(name)
        self.path_lbl = QLabel(path)
        self.path_lbl.setObjectName("muted")
        self.path_lbl.setToolTip(path)
        self.name_lbl.setWordWrap(False)
        self.path_lbl.setWordWrap(False)
        col.addWidget(self.name_lbl)
        col.addWidget(self.path_lbl)
        lay.addLayout(col, stretch=1)

        badge = QLabel(status)
        badge.setObjectName(_STATUS_BADGE.get(status, "muted"))
        self.badge = badge
        lay.addWidget(badge)

        btn = QPushButton("✕")
        btn.setObjectName("del")
        btn.setFixedSize(28, 28)
        btn.setToolTip("从最近列表移除（不会删除工程本身）")
        btn.clicked.connect(lambda: on_delete(path))
        lay.addWidget(btn)

    def resizeEvent(self, event) -> None:  # noqa: N802  Qt 命名
        super().resizeEvent(event)
        w_name = self.name_lbl.width()
        w_path = self.path_lbl.width()
        # 宽度为 0（尚未布局）时不省略，避免把文字清空成空串
        if w_name > 0:
            self.name_lbl.setText(
                self.name_lbl.fontMetrics().elidedText(
                    self._name, Qt.TextElideMode.ElideRight, w_name))
        if w_path > 0:
            self.path_lbl.setText(
                self.path_lbl.fontMetrics().elidedText(
                    self._path, Qt.TextElideMode.ElideMiddle, w_path))


class _PathCard(QFrame):
    """一张路径卡片：序号 + 标题 + 一句说明 + 状态标记。点击发出 clicked。"""

    clicked = Signal()

    def __init__(self, index: str, title: str, desc: str, badge: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)   # 让 QSS 的 :hover 生效
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(240, 132)
        policy = self.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
        policy.setVerticalPolicy(QSizePolicy.Policy.Preferred)
        self.setSizePolicy(policy)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)

        head = QHBoxLayout()
        num = QLabel(index)
        num.setObjectName("h2")
        num.setStyleSheet(f"color: {theme.C_PRIMARY};")
        head.addWidget(num)
        name = QLabel(title)
        name.setObjectName("h2")
        head.addWidget(name, stretch=1)
        if badge:
            tag = QLabel(badge)
            tag.setObjectName("badge-warn")
            tag.setToolTip("该功能尚未实现，点击可查看当前进度与替代路径")
            head.addWidget(tag)
        lay.addLayout(head)

        body = QLabel(desc)
        body.setObjectName("muted")
        lay.addWidget(body, stretch=1)
        harden_window(self)

    def mousePressEvent(self, event) -> None:  # noqa: N802  Qt 命名
        self.clicked.emit()
        super().mousePressEvent(event)


class HomePage(QWidget):
    open_project = Signal(str)        # 工程目录
    delete_recent = Signal(str)       # 工程目录（从最近列表移除）
    new_project = Signal()
    open_settings = Signal(str)       # 目标页：""=常规，plugins=插件与依赖
    use_lite_mode = Signal()          # 一键流水线（建设中）
    open_doctor = Signal()            # 形态诊断仪
    open_knowledge = Signal()         # 迁移知识库
    open_troubleshoot = Signal()      # 排障台

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 32, 40, 28)
        lay.setSpacing(14)

        title = QLabel("跨平台迁移白盒工作台")
        title.setObjectName("h1")
        lay.addWidget(title)
        sub = QLabel("Android → HarmonyOS 白盒迁移：拆 → 画拼图 → 判断 → 填上 → 补缝。"
                     "先选一条路，剩下的交给工作台。")
        sub.setObjectName("muted")
        lay.addWidget(sub)

        # 工作区路径 + 模式徽标 + 设置
        ws_row = QHBoxLayout()
        self.ws_label = QLabel("工作区：—")
        self.ws_label.setObjectName("muted")
        ws_row.addWidget(self.ws_label, stretch=1)
        self.mode_badge = QLabel("专业开发者模式")
        self.mode_badge.setObjectName("badge")
        ws_row.addWidget(self.mode_badge)
        btn_settings = QPushButton("设置")
        btn_settings.clicked.connect(lambda: self.open_settings.emit(""))
        ws_row.addWidget(btn_settings)
        lay.addLayout(ws_row)

        # 五张路径卡片（3 + 2 网格，不是一排按钮）
        grid = QGridLayout()
        grid.setSpacing(12)
        self._cards: list[_PathCard] = []
        handlers = [
            self.use_lite_mode.emit,
            self.new_project.emit,
            self.open_doctor.emit,
            self.open_knowledge.emit,
            self.open_troubleshoot.emit,
        ]
        for i, (idx, name, desc, badge) in enumerate(_PATHS):
            card = _PathCard(idx, name, desc, badge)
            card.clicked.connect(handlers[i])
            row, col = divmod(i, 3)
            grid.addWidget(card, row, col)
            self._cards.append(card)
        lay.addLayout(grid)

        # 依赖轻量提示（不再整块铺列表）
        self.dep_hint = QLabel("")
        self.dep_hint.setObjectName("muted")
        self.btn_dep = QPushButton("去安装")
        self.btn_dep.setVisible(False)
        self.btn_dep.clicked.connect(lambda: self.open_settings.emit("plugins"))
        dep_row = QHBoxLayout()
        dep_row.addWidget(self.dep_hint, stretch=1)
        dep_row.addWidget(self.btn_dep)
        lay.addLayout(dep_row)

        # 最近工程（收在折叠高度里，不抢主视觉；每行含状态徽标 + 删除）
        recent_title = QLabel("最近工程")
        recent_title.setObjectName("h2")
        lay.addWidget(recent_title)
        self.recent = QListWidget()
        self.recent.itemDoubleClicked.connect(self._open_item)
        self.recent.setMaximumHeight(232)
        self.recent.setSpacing(4)
        lay.addWidget(self.recent)
        lay.addStretch(1)

        harden_window(self)

    # ------------------------------------------------------------ 工程

    def set_workspace(self, root: str, mode: str = "pro") -> None:
        self.ws_label.setText(f"工作区：{root}")
        self.ws_label.setToolTip(root)
        self.mode_badge.setText("普通用户模式" if mode == "lite" else "专业开发者模式")

    def set_recent(self, entries: list[dict]) -> None:
        """渲染最近工程：每行名称 + 路径 + 状态徽标 + 删除按钮。

        setItemWidget 必须配 item.setSizeHint，否则行高会塌成默认高度。
        空列表时显示一行灰色占位，避免大片空白。
        """
        self.recent.clear()
        if not entries:
            ph = QListWidgetItem("（暂无最近工程 —— 用上方卡片新建或打开一个）")
            ph.setFlags(ph.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            ph.setSizeHint(QSize(0, 36))
            self.recent.addItem(ph)
            return
        for e in entries:
            path = e.get("path", "")
            name = e.get("name", "") or Path(path).name
            status = _derive_status(Path(path) / "spec.json")
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setSizeHint(QSize(0, 54))   # 宽 0 = 跟随视口宽度
            row = _RecentRow(name, path, status, self._request_delete)
            self.recent.addItem(item)
            self.recent.setItemWidget(item, row)

    def _request_delete(self, path: str) -> None:
        self.delete_recent.emit(path)

    def _open_item(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.open_project.emit(path)

    def _pick_dir(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        d = QFileDialog.getExistingDirectory(self, "选择工程目录（内含 spec.json）")
        if d:
            self.open_project.emit(d)

    # ------------------------------------------------------------ 依赖提示

    def refresh_deps(self, statuses: list | None = None) -> None:
        """只显示一行结论：缺几项 → 去设置安装。列表本身在设置 → 插件与依赖。"""
        if statuses is None:
            self.dep_hint.setText("")
            self.btn_dep.setVisible(False)
            return
        missing: list[str] = []
        for st in statuses:
            ok = bool(getattr(st, "ok", None) if hasattr(st, "ok") else st.get("ok"))
            if ok:
                continue
            name = getattr(st, "name", None) if hasattr(st, "name") else st.get("name")
            missing.append(str(name or "未知依赖"))
        if not missing:
            self.dep_hint.setText("本机依赖已就绪（Java / apktool / SDK 等）")
            self.dep_hint.setStyleSheet(f"color: {theme.C_SUCCESS_TXT};")
            self.btn_dep.setVisible(False)
            return
        text = f"{len(missing)} 项依赖缺失：{'、'.join(missing[:4])}" + \
               ("…" if len(missing) > 4 else "") + " → 去设置安装"
        self.dep_hint.setText(text)
        self.dep_hint.setStyleSheet(f"color: {theme.C_DANGER_TXT};")
        self.dep_hint.setToolTip(plain_text("缺失：" + "、".join(missing)))
        self.btn_dep.setVisible(True)

    def set_dep_loading(self) -> None:
        self.dep_hint.setText("⏳ 正在检测本机依赖…")
        self.dep_hint.setStyleSheet("")
        self.btn_dep.setVisible(False)
