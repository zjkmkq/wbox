"""离屏自检：找出「可能被截断」的 QLabel / 表格列。

存在理由：用户反复反馈"字很多但 UI 很小，字被遮挡"。这类问题靠肉眼看截图容易漏，
必须能量化。本脚本用 Qt 的 fontMetrics().boundingRect() 算出每个可见 QLabel
显示全文所需的宽/高，与实际拿到的宽/高对比，凡是不够的就列出来。

判定规则：
  - 开了自动换行的标签：比"在当前宽度下显示完整所需高度" vs 实际高度
  - 没开换行的标签：比"单行显示完整所需宽度" vs 实际宽度
  - 富文本（含 HTML 标签）按 1.35 倍容差（标签排版与纯文本度量有系统性差异）
  - 有意截断（文本以 … 结尾）与徽标类（objectName=badge*）跳过

用法：
    QT_QPA_PLATFORM=offscreen python scripts/check_text_clip.py [工程目录]
退出码：0=没有疑似截断；1=发现问题（CI 可据此失败）。
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QTableWidget  # noqa: E402

from wbox.gui.mainwin import MainWindow  # noqa: E402
from wbox.gui.settings import SettingsDialog  # noqa: E402
from wbox.gui.uikit import plain_text, required_height, required_width  # noqa: E402

PROJECT = sys.argv[1] if len(sys.argv) > 1 else "."
WIDTH = int(os.environ.get("WBOX_CLIP_WIDTH", "1360"))
HEIGHT = int(os.environ.get("WBOX_CLIP_HEIGHT", "860"))

# 有意省略 / 图标徽标类，不算问题
_ALLOWED_OBJECTS = {"badge", "badge-ok", "badge-warn", "badge-err"}
_RICH_TOLERANCE = 1.35


def _rich(text: str) -> bool:
    return "<" in text and ">" in text


def _collect_labels(root, scope: str, problems: list[str]) -> int:
    checked = 0
    for lab in root.findChildren(QLabel):
        if not lab.isVisible() or lab.width() <= 2 or lab.height() <= 0:
            continue
        raw = lab.text() or ""
        text = plain_text(raw)
        if not text:
            continue
        if lab.objectName() in _ALLOWED_OBJECTS or raw.strip().endswith("…"):
            continue
        checked += 1
        if lab.wordWrap():
            needed = required_height(lab, lab.width())
            limit = (lab.height() + 4) * (_RICH_TOLERANCE if _rich(raw) else 1.0)
            if needed > limit:
                problems.append(
                    f"[纵向截断] {scope} · {type(lab).__name__}({lab.objectName() or '-'}) "
                    f"宽 {lab.width()} 需高 {needed} 实高 {lab.height()} :: {text[:60]}")
        else:
            needed = required_width(lab)
            if needed > lab.width() + 4:
                problems.append(
                    f"[横向截断] {scope} · {type(lab).__name__}({lab.objectName() or '-'}) "
                    f"需宽 {needed} 实宽 {lab.width()} :: {text[:60]}")
    return checked


def _collect_tables(root, scope: str, problems: list[str]) -> int:
    checked = 0
    for table in root.findChildren(QTableWidget):
        if not table.isVisible() or table.width() <= 2:
            continue
        checked += 1
        if not table.wordWrap():
            for r in range(table.rowCount()):
                for c in range(table.columnCount()):
                    item = table.item(r, c)
                    if item is None:
                        continue
                    text = plain_text(item.text())
                    if not text:
                        continue
                    needed = required_width(QLabel(text))
                    width = table.columnWidth(c)
                    if width > 0 and needed > width + 4:
                        problems.append(
                            f"[表格窄列] {scope} · 行{r}列{c} 需宽 {needed} 列宽 {width} "
                            f":: {text[:60]}")
                        break
    return checked


def main() -> int:
    app = QApplication(sys.argv[:1])
    from wbox.gui.theme import apply_theme

    apply_theme(app)
    win = MainWindow()
    win.resize(WIDTH, HEIGHT)
    win.show()
    if PROJECT and os.path.isdir(PROJECT):
        try:
            win.open_project(PROJECT)
        except Exception:  # noqa: BLE001  打不开也要继续检查首页
            pass
    app.processEvents()

    problems: list[str] = []
    total = 0

    # 1. 主窗每个页面（逐个切到前台才可见、才有真实几何）
    for i in range(win.root.count()):
        win.root.setCurrentIndex(i)
        app.processEvents()
        total += _collect_labels(win, f"主窗页#{i}", problems)
        total += _collect_tables(win, f"主窗页#{i}", problems)

    # 2. 工作区：资源栏四个 tab + 六步页面
    win.root.setCurrentIndex(win._root_index["workspace"])
    if win.session is not None:
        for t in range(win.inventory.count()):
            win.inventory.setCurrentIndex(t)
            app.processEvents()
            total += _collect_labels(win, f"资源栏 tab#{t}", problems)
            total += _collect_tables(win, f"资源栏 tab#{t}", problems)
        for sid, page in win._pages.items():
            win.goto_step(sid)
            app.processEvents()
            total += _collect_labels(win, f"步骤 {sid}", problems)
            total += _collect_tables(win, f"步骤 {sid}", problems)

    # 3. 设置对话框（三个分页；插件页不触发检测，只查布局）
    dlg = SettingsDialog(win.cfg, win)
    for i in range(dlg.tabs.count()):
        dlg.tabs.setCurrentIndex(i)
        app.processEvents()
        total += _collect_labels(dlg, f"设置页#{i}", problems)
        total += _collect_tables(dlg, f"设置页#{i}", problems)
    dlg.close()

    win._wait_threads()
    print(f"已检查可见 QLabel/表格：{total} 个控件参与度量")
    if not problems:
        print("TEXT CLIP OK —— 未发现疑似截断")
        return 0
    print(f"发现 {len(problems)} 处疑似截断：")
    for p in problems:
        print("  · " + p)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
