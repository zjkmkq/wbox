"""wbox.gui.uikit —— 全局「文字不被遮挡」加固工具集。

存在理由（2026-10-27 全局遮挡治理）：用户反复反馈"字很多但 UI 很小，导致字被遮挡"。
根因是三条 Qt 默认行为叠加：

1. QLabel 默认不换行，被父布局压窄后 Qt 直接 elide 成 "…" —— 信息静默丢失，
   用户既看不到全文，也得不到"这里被截了"的任何提示。
2. QTableWidgetItem 没有 setWordWrap（换行是 QTableView 级属性），表格窄列必截。
3. 窗体/对话框不设 setMinimumSize，内容超过窗口高度时直接被裁掉，无法滚动。

修补一处容易、杜绝一类难。所以把防遮挡收敛成本模块的一组函数 + 一条硬规则：
**任何窗体/对话框构建完成后必须调一次 harden_window()**。这样新增控件自动受保护，
不需要每处各写一遍。配套 scripts/check_text_clip.py 做机器自检。
"""

from __future__ import annotations

import re
from typing import Iterable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QSizePolicy,
    QListWidget,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

__all__ = [
    "plain_text",
    "wrap_label",
    "muted_label",
    "harden_label",
    "harden_labels",
    "harden_item_views",
    "configure_table",
    "harden_window",
    "install_text_guard",
    "required_width",
    "required_height",
]

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# 这些 objectName 的标签是徽标/图标类短文本，不需要 tooltip 全文（避免噪音）
_NO_TOOLTIP_OBJECTS = frozenset({"badge", "badge-ok", "badge-warn", "badge-err"})


def plain_text(text: str) -> str:
    """去掉 HTML 标签并压空白，用于 tooltip（tooltip 里 <br> 只会显示成字面量）。"""
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", text or "")).strip()


def wrap_label(
    text: str,
    *,
    object_name: str = "",
    tooltip: str = "",
    min_width: int = 0,
    parent: QWidget | None = None,
) -> QLabel:
    """造一个「不会遮挡自己的文字」的 QLabel：换行 + 可收缩 + 全文 tooltip。"""
    lab = QLabel(text, parent) if parent is not None else QLabel(text)
    if object_name:
        lab.setObjectName(object_name)
    if min_width > 0:
        lab.setMinimumWidth(min_width)
    harden_label(lab, tooltip=tooltip)
    return lab


def muted_label(text: str, *, min_width: int = 0, parent: QWidget | None = None) -> QLabel:
    """次级说明文字：muted 配色 + 自动换行。"""
    return wrap_label(text, object_name="muted", min_width=min_width, parent=parent)


def harden_label(label: QLabel, *, tooltip: str = "") -> None:
    """单个 QLabel 加固。

    - 开自动换行（wordWrap）：宽度不够时折行而不是截尾。
    - 尺寸策略 (Preferred, Minimum)：横向可被压缩、纵向随内容增高，
      避免父布局把它挤成 1 像素宽或固定高度导致下半截消失。
    - 全文 tooltip：即便极端窄也能悬停看全。
    """
    label.setWordWrap(True)
    policy = label.sizePolicy()
    policy.setHorizontalPolicy(QSizePolicy.Policy.Preferred)
    policy.setVerticalPolicy(QSizePolicy.Policy.Minimum)
    label.setSizePolicy(policy)
    # 换行标签对中文的 minimumSizeHint 可以低到"一个字的宽度"，
    # 于是短标题（如「鸿蒙工程目标目录：」）会在同行有 QLineEdit 时被压成竖排。
    # 给一个"自然宽度的下限（封顶 200px）"：短标签保整行，长段落仍可收缩换行。
    hint_w = label.sizeHint().width()
    if hint_w > 0:
        floor = min(hint_w, _LABEL_MIN_WIDTH_CAP)
        if label.minimumWidth() < floor:
            label.setMinimumWidth(floor)
    if tooltip:
        label.setToolTip(tooltip)
        return
    if label.objectName() in _NO_TOOLTIP_OBJECTS:
        return
    if not label.toolTip():
        text = plain_text(label.text())
        if text:
            label.setToolTip(text)


def harden_labels(root: QWidget) -> int:
    """递归加固 root 下全部 QLabel（含嵌套布局里的）。返回处理数量。"""
    count = 0
    if isinstance(root, QLabel):
        harden_label(root)
        count += 1
    for lab in root.findChildren(QLabel):
        harden_label(lab)
        count += 1
    return count


def _iter_tree_items(tree: QTreeWidget) -> Iterable[QTreeWidgetItem]:
    stack: list[QTreeWidgetItem] = []
    for i in range(tree.topLevelItemCount()):
        stack.append(tree.topLevelItem(i))
    while stack:
        item = stack.pop()
        yield item
        for j in range(item.childCount()):
            stack.append(item.child(j))


def _fill_item_tooltips(view: QWidget) -> None:
    """给表格/树的每个单元格补全文 tooltip（窄列悬停可见）。

    **必须 blockSignals**：部分步骤页把表格的 itemChanged 接到了"保存 spec +
    刷新三栏"上；不屏蔽信号时，补 tooltip 会被当成用户改数据 → spec 落盘 →
    三栏刷新 → 新的 Show 事件 → 再补 tooltip，形成死循环（2026-10-27 实测：
    切回工作区时界面卡死，栈里能看到 plan_step._on_changed → session.save）。
    """
    view.blockSignals(True)
    try:
        if isinstance(view, QTableWidget):
            for r in range(view.rowCount()):
                for c in range(view.columnCount()):
                    item = view.item(r, c)
                    if item is None:
                        continue
                    if not item.toolTip():
                        text = plain_text(item.text())
                        if text:
                            item.setToolTip(text)
            return
        if isinstance(view, QTreeWidget):
            for item in _iter_tree_items(view):
                for c in range(view.columnCount()):
                    text = plain_text(item.text(c))
                    if text and not item.toolTip(c):
                        item.setToolTip(c, text)
    finally:
        view.blockSignals(False)


_MIN_SECTION = 72   # 列最小宽度：小于它就变成"一字一行"的竖排，比截断更糟
# 标签的宽度下限封顶：短标签按自然宽度整行显示，长段落最多占 200px 就允许收缩换行
_LABEL_MIN_WIDTH_CAP = 200


def harden_item_views(root: QWidget) -> int:
    """递归加固表格/树：开换行 + 行高自适应 + 单元格全文 tooltip。

    关键一行是 setMinimumSectionSize：列被挤到几十像素时，开了 wordWrap 的中文
    会变成"每行一个字"的竖条（比截断更难读）。给列设下限后，空间不够时出现
    横向滚动条，而不是把文字压成竖排。
    """
    count = 0
    views: list[QWidget] = []
    views.extend(root.findChildren(QTableWidget))
    views.extend(root.findChildren(QTreeWidget))
    for view in views:
        # 单元格换行是视图级属性：QTableWidgetItem 没有 setWordWrap
        view.setWordWrap(True)
        header = getattr(view, "horizontalHeader", None)
        if callable(header):
            head = header()
            if head is not None and head.minimumSectionSize() < _MIN_SECTION:
                head.setMinimumSectionSize(_MIN_SECTION)
        if isinstance(view, QTreeWidget):
            # uniformRowHeights 是 QTreeView 的属性（QTableView 没有），
            # 关掉后各行才能按内容高度独立增长
            view.setUniformRowHeights(False)
        else:
            view.blockSignals(True)
            try:
                view.resizeRowsToContents()   # 重算行高同样不许触发业务信号
            finally:
                view.blockSignals(False)
        _fill_item_tooltips(view)
        count += 1
    for lst in root.findChildren(QListWidget):
        # 列表项不支持换行：至少保证悬停能看到全文
        lst.blockSignals(True)
        try:
            for i in range(lst.count()):
                item = lst.item(i)
                if item is not None and not item.toolTip():
                    text = plain_text(item.text())
                    if text:
                        item.setToolTip(text)
        finally:
            lst.blockSignals(False)
        count += 1
    return count


def configure_table(
    table: QTableWidget,
    headers: list[str],
    stretch_cols: Iterable[int] = (),
    min_section_size: int = 56,
) -> None:
    """统一列宽策略：长列 Stretch（吃剩余空间并换行），短列 ResizeToContents。

    顺带开换行、设最小段宽（防被缩成 0 导致整列"消失"）。
    """
    stretch = set(stretch_cols)
    table.setWordWrap(True)
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    header = table.horizontalHeader()
    header.setMinimumSectionSize(min_section_size)
    for c in range(len(headers)):
        mode = header.ResizeMode.Stretch if c in stretch else header.ResizeMode.ResizeToContents
        header.setSectionResizeMode(c, mode)


_IN_HARDEN = False


def harden_window(root: QWidget) -> int:
    """窗体/对话框构建完成后的总闸：标签 + 表格/树一起加固。返回处理控件数。

    带重入保护：加固过程中可能间接触发新的 Show 事件（例如某页面 refresh 后
    又弹出子控件），没有这道闸会递归加固、越陷越深。
    """
    global _IN_HARDEN
    if _IN_HARDEN:
        return 0
    _IN_HARDEN = True
    try:
        return harden_labels(root) + harden_item_views(root)
    finally:
        _IN_HARDEN = False


# ---------------------------------------------------------------- 全局守卫

_GUARD_FLAG = "_wbox_text_guard_installed"


class _TextGuard(QObject):
    """全局事件过滤器：任何控件**显示时**就地加固它里面的 QLabel / 表格。

    为什么需要它：大量标签是运行时才建的（步骤页刷新出的提示、动态加的红字警告、
    延迟创建的对话框），只在窗体构造后调一次 harden_window() 覆盖不到——这正是
    "修完又复发"的根因。挂在 QApplication 上监听 Show 事件，凡新露面的控件
    过一遍加固，代价是几百次属性设置，可忽略。
    """

    def eventFilter(self, obj, event) -> bool:  # noqa: N802  Qt 命名
        if event.type() == QEvent.Type.Show and isinstance(obj, QWidget):
            # 子控件数量没变就跳过：同一个窗口反复显示时不做重复加固
            signature = len(obj.findChildren(QWidget))
            if getattr(obj, "_wbox_harden_sig", -1) != signature:
                obj._wbox_harden_sig = signature
                harden_window(obj)
        return False


def install_text_guard(app: QObject | None = None) -> bool:
    """安装全局加固守卫（幂等）。返回是否真的安装了。"""
    if app is None:
        app = QApplication.instance()
    if app is None or getattr(app, _GUARD_FLAG, False):
        return False
    guard = _TextGuard(app)
    app.installEventFilter(guard)
    setattr(app, _GUARD_FLAG, True)
    app.setProperty("_wbox_text_guard_obj", guard)   # 持有引用，防被 GC
    return True


# ---------------------------------------------------------------- 度量（自检用）

def required_width(label: QLabel) -> int:
    """标签不换行时显示全文所需的像素宽度。"""
    metrics = QFontMetrics(label.font())
    return metrics.boundingRect(plain_text(label.text())).width() + 4


def required_height(label: QLabel, width: int) -> int:
    """标签在给定宽度下换行显示全文所需的像素高度。"""
    if width <= 0:
        return 0
    metrics = QFontMetrics(label.font())
    rect = metrics.boundingRect(
        0, 0, width, 1 << 20, int(Qt.TextFlag.TextWordWrap), plain_text(label.text())
    )
    return rect.height() + 4


def set_table_item(item: QTableWidgetItem, text: str) -> QTableWidgetItem:
    """建表格单元：顺带补全文 tooltip（调用方不必记得写）。"""
    item.setText(text)
    item.setToolTip(plain_text(text))
    return item
