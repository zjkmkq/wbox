"""离屏截图脚本：验证深色 IDE 主题真实落地（QSS 生效 + 像素抽检）。

用法：python scripts/preview_theme.py [工程目录]
产物：D:/theme-preview/ 下三张 PNG（主窗全景 / 步骤导航 / 缝状态板）。
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import wbox.gui.mainwin  # noqa: E402  触发五步注册
from wbox.gui.mainwin import MainWindow  # noqa: E402
from wbox.gui.session import ProjectSession  # noqa: E402
from wbox.gui.theme import apply_theme  # noqa: E402

PROJECT = sys.argv[1] if len(sys.argv) > 1 else "."
OUT = "D:/theme-preview"


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    app = QApplication(sys.argv[:1])
    apply_theme(app, "dark")  # 像素抽检断言深空蓝底，固定深色

    session = ProjectSession(PROJECT)
    session.load()

    win = MainWindow()
    win.open_project(str(session.project_dir))
    win.resize(1600, 900)
    win.show()
    app.processEvents()

    # 走到第 5 步，让缝状态板有内容
    win.goto_step("seal")
    app.processEvents()

    full = win.grab().save(f"{OUT}/main_full.png")
    print(f"[ok] 主窗全景 → {OUT}/main_full.png ({full})")

    # 步骤导航（含 checked 态）
    btn = win.step_buttons.get("seal")
    if btn is not None:
        ok = btn.grab().save(f"{OUT}/step_nav.png")
        print(f"[ok] 步骤导航（当前步高亮）→ {OUT}/step_nav.png ({ok})")

    # 缝状态板（右栏 records 面板）
    records = win.records
    ok = records.grab().save(f"{OUT}/records.png")
    print(f"[ok] 右栏记录面板 → {OUT}/records.png ({ok})")

    # 像素抽检：窗口底色应为深空蓝 #0C1017（容差 ±12）
    img: QImage = win.grab().toImage()
    px = img.pixelColor(8, 8)
    print(f"[px] 窗口底色 = ({px.red()},{px.green()},{px.blue()})  期望 ≈ (12,16,23)")
    assert abs(px.red() - 12) <= 14 and abs(px.green() - 16) <= 14 and abs(px.blue() - 23) <= 14, \
        f"底色未切换到深色主题：{(px.red(), px.green(), px.blue())}"
    print("[ok] 像素抽检通过：深色主题已生效")

    print("PREVIEW OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
