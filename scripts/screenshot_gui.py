"""离屏截图：把每个页面 QWidget.grab() 存成 PNG，供人工肉眼验收布局。

存在理由：遮挡/塌陷这类问题文字报告说不清，必须看图。本脚本在 offscreen 下
把首页、工作区（含六步）、形态诊断仪、知识库、排障台、设置三个分页全部截一遍，
输出到 scripts/shots/（可用环境变量 WBOX_SHOTS 改目录）。

用法：
    QT_QPA_PLATFORM=offscreen python scripts/screenshot_gui.py [工程目录] [--deps]
    --deps  额外跑一次依赖检测，让「插件与依赖」页有真实数据（会连网/跑子进程）
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

PROJECT = ""
WITH_DEPS = "--deps" in sys.argv
for arg in sys.argv[1:]:
    if not arg.startswith("--") and not PROJECT:
        PROJECT = arg

OUT_DIR = os.environ.get("WBOX_SHOTS") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "shots")
WIDTH = int(os.environ.get("WBOX_SHOT_W", "1440"))
HEIGHT = int(os.environ.get("WBOX_SHOT_H", "900"))


def main() -> int:
    # 截图脚本强制走"内嵌浏览器不可用"分支：WebEngine 首次加载 bing 会拖很久，
    # 而且离屏/无 GPU 环境里可能直接崩，截图流程不该被它卡住。
    os.environ.setdefault("WBOX_NO_WEBENGINE", "1")

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    # 与 gui/__main__.py 保持一致：WebEngine 需要共享 OpenGL 上下文
    if hasattr(Qt.ApplicationAttribute, "AA_ShareOpenGLContexts"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    app = QApplication(sys.argv[:1])
    from wbox.gui.mainwin import MainWindow
    from wbox.gui.settings import SettingsDialog
    from wbox.gui.theme import apply_theme

    apply_theme(app)
    os.makedirs(OUT_DIR, exist_ok=True)

    win = MainWindow()
    win.resize(WIDTH, HEIGHT)
    win.show()
    if PROJECT and os.path.isdir(PROJECT):
        try:
            win.open_project(PROJECT)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 打开工程失败（继续截首页）：{e}")
    app.processEvents()

    saved: list[str] = []

    def shot(widget, name: str) -> None:
        widget.show()
        app.processEvents()
        path = os.path.join(OUT_DIR, f"{name}.png")
        pix = widget.grab()
        pix.save(path, "PNG")
        saved.append(path)
        print(f"[shot] {path}  {pix.width()}x{pix.height()}")

    # 1. 首页（五张路径卡片）
    win.root.setCurrentIndex(win._root_index["home"])
    app.processEvents()
    shot(win, "01-home")

    print("[phase] 1-home done", flush=True)
    # 2. 工作区 + 六步；顺带截资源栏各 tab
    if win.session is not None:
        win.root.setCurrentIndex(win._root_index["workspace"])
        app.processEvents()
        shot(win, "02-workspace")
        for t in range(win.inventory.count()):
            win.inventory.setCurrentIndex(t)
            app.processEvents()
            shot(win, f"03-inventory-tab{t}")
        for sid in list(win._pages):
            win.goto_step(sid)
            app.processEvents()
            shot(win, f"04-step-{sid}")

    print("[phase] 2-4 workspace/steps done", flush=True)
    # 3. 形态诊断仪 / 知识库 / 排障台
    win.show_page("doctor")
    app.processEvents()
    shot(win, "05-doctor")
    win.show_page("knowledge")
    app.processEvents()
    shot(win, "06-knowledge")
    shot(win.knowledge_page, "06b-knowledge-meta")   # 三条铁律区单独放大确认不挤竖排
    win.show_page("troubleshoot")
    win.trouble_page.wait_thread(5000)
    app.processEvents()
    shot(win, "07-troubleshoot")
    # 3.1 工具箱（五个动作的可用性要靠图验收：缺什么按钮就是灰的）
    win.show_page("tools")
    win.tools_page.wait_thread(5000)
    app.processEvents()
    shot(win, "07b-tools")

    print("[phase] 5-7 pages done", flush=True)
    # 3.5 右栏帮助中心（帮助 / 记录两个 Tab）+ 教程阅读窗 + 联网降级窗
    if win.session is not None:
        win.root.setCurrentIndex(win._root_index["workspace"])
        win.help.setCurrentIndex(0)
        win.help.help_page.search.setText("白屏")
        win.help.help_page._do_search()
        app.processEvents()
        shot(win, "09-help-center")
        win.help.setCurrentIndex(1)
        app.processEvents()
        shot(win, "09-help-records")
        win.help.setCurrentIndex(0)

    print("[phase] 9 help done", flush=True)
    from wbox import tutorial as tut_mod
    tuts = tut_mod.load_tutorials()
    if tuts:
        from wbox.gui.panels.help import TutorialDialog

        dlg_t = TutorialDialog(tuts[min(4, len(tuts) - 1)], win)
        dlg_t.resize(980, 780)
        dlg_t.show()
        app.processEvents()
        shot(dlg_t, "10-tutorial")
        dlg_t.close()

    print("[phase] 10 tutorial done", flush=True)
    from wbox.gui.webview import OnlineSearchDialog

    dlg_o = OnlineSearchDialog("Phaser tint 白屏", win)
    dlg_o.resize(820, 560)
    dlg_o.show()
    app.processEvents()
    shot(dlg_o, "11-online-fallback")
    dlg_o.close()

    print("[phase] 11 online done", flush=True)
    # 4. 设置三个分页
    dlg = SettingsDialog(win.cfg, win)
    dlg.resize(900, 720)
    if WITH_DEPS:
        dlg.refresh_plugins()
        dlg.plugins_page.wait_threads(30000)
    for i, name in enumerate(("general", "plugins", "advanced")):
        dlg.tabs.setCurrentIndex(i)
        dlg.show()
        app.processEvents()
        shot(dlg, f"08-settings-{name}")
    dlg.close()

    win._wait_threads()
    print(f"SHOTS OK —— {len(saved)} 张，目录：{OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
