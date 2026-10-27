"""GUI 入口：python -m wbox.gui

全局异常钩子（写死）：未捕获异常弹窗展示摘要，不静默死亡、不裸 traceback 刷屏。

--selftest（冷启动自检）：
    打包后的 WBox.exe 是 windowed 程序，stdout 看不到，无法用 print 做验收。
    所以自检把结论写到 %LOCALAPPDATA%/WBox/logs/selftest.log，并用退出码回话：
    0=全部通过，1=有断言失败。验收脚本（scripts/verify_exe.py）据此判断
    "模板和教程是不是真的进了包、五个入口是不是都能打开"。
"""

from __future__ import annotations

import os
import sys
import traceback


def _excepthook(exc_type, exc_value, exc_tb) -> None:
    from PySide6.QtWidgets import QApplication, QMessageBox
    text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))[-2000:]
    if QApplication.instance() is not None:
        QMessageBox.critical(None, "程序出错", text)
    else:
        sys.stderr.write(text)
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def _run_selftest() -> int:
    """离屏把五个入口与两个资源库都过一遍，结论写日志 + 退出码。

    这**不是**测试替代品，只是"打包产物里资源没丢"的判据：冻结态最容易翻车的
    就是 datas 少打一个目录 —— 界面能开、列表全空，肉眼很难发现。
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("WBOX_NO_WEBENGINE", "1")
    # windowed exe 的 stdout 在 Windows 上默认按 GBK 编码，中文会变乱码；
    # 日志文件本身是 UTF-8，这里顺手把控制台也统一（拿不到 stdout 就跳过）
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass

    lines: list[str] = []
    ok = True

    def check(label: str, condition: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and bool(condition)
        lines.append(f"[{'ok' if condition else 'FAIL'}] {label}{('：' + detail) if detail else ''}")

    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication

        if hasattr(Qt.ApplicationAttribute, "AA_ShareOpenGLContexts"):
            QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
        app = QApplication(sys.argv[:1])

        from wbox import shape as shape_mod
        from wbox import tutorial as tutorial_mod
        from wbox.gui.mainwin import MainWindow
        from wbox.gui.theme import apply_theme

        apply_theme(app)

        shapes = shape_mod.load_shapes(force=True)
        check("形态模板", bool(shapes), f"{len(shapes)} 个：{', '.join(s.get('shape_id', '?') for s in shapes)}")
        rules = shape_mod.meta_rules()
        check("三条铁律", len(rules) == 3, "R1/R2/R3" if len(rules) == 3 else f"实际 {len(rules)} 条")

        tuts = tutorial_mod.load_tutorials(force=True)
        check("教程库", bool(tuts), f"{len(tuts)} 篇")
        check("教程按步骤匹配", bool(tutorial_mod.by_step("extract")),
              f"extract 命中 {len(tutorial_mod.by_step('extract', limit=99))} 篇")

        win = MainWindow()
        win.resize(1280, 860)
        win.show()
        app.processEvents()

        # 内嵌浏览器：能导入就用内嵌，导不进就退系统浏览器。两种都不算失败，
        # 但要如实记下当前产物属于哪一种（瘦身包天然是后者）。
        try:
            import PySide6.QtWebEngineWidgets  # noqa: F401  仅探测可导入性
            engine = "可用（内嵌 Bing）"
        except Exception:  # noqa: BLE001
            engine = "不可用 → 联网检索走系统浏览器（降级路径）"
        check("内嵌浏览器", True, engine)

        for page in ("home", "doctor", "knowledge", "troubleshoot", "tools"):
            win.show_page(page)
            app.processEvents()
            check(f"入口 {page}", win.root.currentWidget() is not None)
        from wbox.gui.steps import STEPS

        check("六步注册", len(STEPS) == 6, "、".join(s.step_id for s in STEPS))

        # 帮助中心：情境教程非空 = tutorials 真的读到了
        win.help.set_step("extract", "① 拆")
        app.processEvents()
        check("右栏情境教程", win.help.help_page.tut_list.count() > 0,
              f"{win.help.help_page.tut_list.count()} 篇")

        win._wait_threads()
        for w in (win,):
            try:
                w.close()
            except Exception:  # noqa: BLE001
                pass
    except Exception as e:  # noqa: BLE001
        ok = False
        lines.append(f"[FAIL] 自检异常：{e}")
        lines.append(traceback.format_exc()[-1500:])

    lines.append("SELFTEST OK" if ok else "SELFTEST FAILED")
    text = "\n".join(lines)
    try:
        from wbox.paths import logs_dir

        log_path = logs_dir() / "selftest.log"
        log_path.write_text(text, encoding="utf-8")
        text += f"\n（已写入 {log_path}）"
    except Exception:  # noqa: BLE001  写不了日志也不能让自检崩
        pass
    sys.stdout.write(text + "\n")
    sys.stdout.flush()
    return 0 if ok else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return _run_selftest()

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from wbox.gui.mainwin import MainWindow
    from wbox.gui.theme import apply_theme
    from wbox.gui.uikit import install_text_guard

    sys.excepthook = _excepthook

    # 帮助中心的内嵌浏览器（QtWebEngine）依赖共享 OpenGL 上下文：
    # 不加这行在部分机器上 WebEngine 会黑屏。必须在 QApplication 创建前设置。
    if hasattr(Qt.ApplicationAttribute, "AA_ShareOpenGLContexts"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    app = QApplication(sys.argv)
    app.setApplicationName("WBox")
    apply_theme(app)
    install_text_guard(app)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
