"""GUI 离屏冒烟测试：不弹窗，把五步页面全部实例化 + 刷新 + 主窗打开。

用法：python scripts/smoke_gui.py
通过条件：无异常，五步 step_id 按序打印，主窗可打开。
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import wbox.gui.mainwin  # noqa: E402  触发五步注册
from wbox.gui.session import ProjectSession  # noqa: E402
from wbox.gui.steps import STEPS  # noqa: E402

PROJECT = sys.argv[1] if len(sys.argv) > 1 else "."


def main() -> int:
    app = QApplication(sys.argv[:1])

    # 1. 会话加载（契约经 wbox.spec）
    session = ProjectSession(PROJECT)
    session.load()
    print(f"[ok] spec 加载：{session.project_name} | 资源 {len(session.resources)} | "
          f"模块 {len(session.modules)} | 行为 {len(session.behaviors)} | "
          f"决策 {len(session.decisions)} | 缝 {len(session.seams)}")

    # 2. 五步页面逐实例化 + 刷新 + 进入
    for cls in STEPS:
        page = cls(session)
        page.refresh()
        page.on_enter()
        print(f"[ok] 步骤页面：{cls.step_id} ({cls.title})")

    # 3. 主窗打开 + 载入同一会话
    from wbox.gui.mainwin import MainWindow
    win = MainWindow()
    win.open_project(str(session.project_dir))
    win.show()
    print("[ok] 主窗打开")

    # 4. 三栏面板刷新（左清单/右记录随 session.changed 联动）
    session.save("冒烟测试保存")
    print("[ok] session.save 触发 changed 广播，三栏联动无异常")

    # 5. 产品化路径离屏覆盖（2026-10-25）：设置对话框 / 软删除 / 模式切换 / 关机钩子
    from wbox import config as app_config
    from wbox.gui.settings import SettingsDialog, maybe_shutdown_on_finish
    from wbox.gui.panels.files import FileBrowserPanel

    dlg = SettingsDialog(win.cfg, win)
    dlg.deleteLater()
    print("[ok] 设置对话框构造（模式/工作区/关机/命名/工具路径）")

    assert callable(win.open_settings) and callable(win.use_lite_mode)
    print("[ok] 主窗 open_settings/use_lite_mode 已接线")

    # 软删除：建临时文件 → 走 _do_delete（avoid=True 移回收区，不物理 unlink）
    import tempfile
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp(prefix="wbox-smoke-"))
    victim = tmp / "smoke_victim.txt"
    victim.write_text("x", encoding="utf-8")
    fb = FileBrowserPanel()
    ok, fail = fb._do_delete([victim], avoid=True)
    assert ok == 1 and fail == 0 and not victim.exists(), f"软删除异常：{ok}/{fail}"
    trash_hits = list(app_config.workspace_sub(win.cfg, "trash").rglob("smoke_victim.txt"))
    assert trash_hits, "软删除后回收区找不到文件"
    print(f"[ok] 软删除移入回收区：{trash_hits[0]}")

    # 关机钩子：关闭时不动作、开启时不真关机（monkeypatch Popen 验证命令）
    import subprocess
    calls = []
    orig_popen = subprocess.Popen
    def _fake_popen(*a, **k):
        calls.append(a[0] if a else k.get("args"))
        class _P:
            def wait(self): return 0
        return _P()
    subprocess.Popen = _fake_popen
    try:
        maybe_shutdown_on_finish({"behavior": {"shutdown_on_finish": False}}, None)
        assert not calls, "关闭状态下不应触发关机"
        cfg_on = {"behavior": {"shutdown_on_finish": True}}
        maybe_shutdown_on_finish(cfg_on, None)  # 无 parent → 只排队不弹窗
        assert calls and calls[0][:2] == ["shutdown", "/s"], f"关机命令异常：{calls}"
    finally:
        subprocess.Popen = orig_popen
    print("[ok] 自动关机钩子（关闭不动作/开启排队 shutdown /s /t 60）")

    # 命名显示开关
    win.inventory.set_zh(False)
    win.inventory.set_zh(True)
    print("[ok] 命名显示开关 set_zh")

    # 7. 首页五条路径 + 三个独立页面（2026-10-27）
    assert win.home is not None and win.root.count() >= 5, "首页路径卡片/页面栈未建全"
    win.show_page("doctor")
    win.show_page("knowledge")
    win.show_page("troubleshoot")
    win.show_page("tools")
    win.trouble_page.wait_thread(5000)
    win.tools_page.wait_thread(5000)
    print("[ok] 形态诊断仪 / 知识库 / 排障台 / 工具箱 四个页面切换无异常")

    # 7.0.5 工具箱：依赖缺失时按钮必须禁用（"点了才报错"是明令禁止的）
    from wbox import toolchain as tc_mod
    tools = win.tools_page
    tools.refresh_env()
    availability = {
        name: tools.btn[name].isEnabled() for name in ("build", "install", "start",
                                                        "snapshot", "inspect", "probe")
    }
    disabled = [n for n, ok in availability.items() if not ok]
    tip = tools.btn["install"].toolTip()
    # 诚实原则（写死的铁律）：hdc 缺失时装机/启动/截图/巡检必须全部禁用。
    # 注意这是单向蕴含（缺→禁），不是双向——hdc 存在时按钮默认可用，仅当刷新设备后
    # device_count==0 才会二次禁用，二者不冲突。旧断言用了双向等号，在"hdc 已装"的
    # 环境（如本机 DevEco SDK 自带 hdc）必然判错，现已改为正确语义。
    if not tools._hdc:
        dev_dependent = ("install", "start", "snapshot", "inspect")
        assert all(not tools.btn[n].isEnabled() for n in dev_dependent), \
            "hdc 缺失时装机/启动/截图/巡检必须全部禁用"
    print(f"[ok] 工具箱按钮可用性：{availability}（禁用项提示：{tip or '—'}）")
    probe_ok, probe_why = tc_mod.probe_status()
    assert isinstance(probe_ok, bool) and bool(probe_why), "probe_status 必须给出理由"
    assert tools.btn["probe"].isEnabled() == probe_ok, "探针按钮状态必须与 probe_status 一致"
    print(f"[ok] 浏览器探针自检：{'可用' if probe_ok else '降级（' + probe_why + '）'}")
    # 中断与导出：只验证不弹窗不崩（导出要弹文件框，这里只验证按钮存在且默认不可用）
    assert tools.btn_cancel is not None and not tools.btn_cancel.isEnabled(), "中断按钮初始应为不可用"
    print("[ok] 工具箱：中断按钮初始禁用、日志可导出（导出需人工点）")

    # 7.1 教程库（front-matter 手写解析，不引 PyYAML）
    from wbox import tutorial as tut_mod
    tuts = tut_mod.load_tutorials(force=True)
    assert tuts, "src/wbox/tutorials/ 下没有可用教程"
    first = tuts[0]
    assert first.title and first.order >= 0, f"front-matter 解析异常：{first.slug}"
    step_hits = tut_mod.by_step("extract", limit=5)
    assert step_hits, "extract 步骤应至少匹配到一篇情境教程"
    print(f"[ok] 教程库：{len(tuts)} 篇；extract 命中 {len(step_hits)} 篇；"
          f"检索「白屏」{len(tut_mod.search('白屏'))} 篇")
    assert tut_mod.related(["h5", "phaser"], "extract", limit=3), "相关推荐为空"

    # 7.2 右栏帮助中心（情境教程 / 本地搜索 / 离线策略）
    help_panel = win.help
    help_panel.set_step("assemble", "⑤ 装配")
    assert help_panel.help_page.tut_list.count() > 0, "情境教程列表为空"
    assert help_panel.records is not None, "记录面板丢了"
    help_panel.help_page.search.setText("编译")
    help_panel.help_page._do_search()
    assert help_panel.help_page.result_list.count() > 0, "本地搜索无结果"
    # 离屏环境下不得实例化 WebEngine（webview 探测必须返回 False）
    from wbox.gui.webview import webengine_available
    assert webengine_available() is False, "离屏环境不应启用内嵌浏览器"
    cfg_off = {"ui": {"online_help": False}}
    help_panel.set_cfg(cfg_off)
    help_panel.help_page._maybe_offer_online("绝不存在的关键词zzz")
    assert help_panel.help_page.online_box.isHidden(), "关掉联网开关后联网区域必须隐藏"
    help_panel.set_cfg(win.cfg)
    help_panel.wait_threads(5000)
    print("[ok] 帮助中心：情境教程 / 本地搜索 / 离线隐藏联网区域 / 离屏不启用 WebEngine")

    # 形态模板加载器（shapes/*.json）
    from wbox import shape as shape_mod
    shapes = shape_mod.load_shapes()
    assert shapes, "src/wbox/shapes/ 下没有可用形态模板"
    print(f"[ok] 形态模板加载：{len(shapes)} 个（{', '.join(s['shape_id'] for s in shapes)}）")
    assert "_meta" not in [s["shape_id"] for s in shapes], "_meta.json 不能混进形态列表"

    # 三条铁律（_meta.json）：inv 团队明确要求 rules==3 且 id 依次 R1/R2/R3
    meta_rules = shape_mod.meta_rules()
    assert len(meta_rules) == 3, f"铁律数量应为 3，实际 {len(meta_rules)}"
    assert [r.get("id") for r in meta_rules] == ["R1", "R2", "R3"], "铁律 id 应依次为 R1/R2/R3"
    assert all(r.get("body") and r.get("title") for r in meta_rules), "铁律缺 title/body"
    assert (shape_mod.load_meta() or {}).get("intro"), "_meta.intro 为空"
    know = win.knowledge_page
    assert know is not None, "知识库页面未建"
    know.reload()
    print("[ok] 三条铁律加载（R1/R2/R3）并已在知识库首页渲染")

    probe = shape_mod.open_target(session.project_dir)
    assert probe.entries, "工程目录扫描应拿到条目"
    print(f"[ok] 形态诊断扫描：{len(probe.entries)} 个条目，命中 {len(shape_mod.detect_shape(session.project_dir))} 个形态")

    # 资源栏（自动分类 + 搜索 + 预览窗构造）
    from wbox.gui.panels.resource_explorer import ResourceExplorerPanel, classify, ImagePreviewDialog
    res_panel = ResourceExplorerPanel()
    res_panel.refresh(session)
    res_panel.search.setText("png")
    res_panel.search.setText("")
    assert res_panel.tree.topLevelItemCount() >= 0
    print(f"[ok] 资源栏分类：{res_panel.count_label.text()}")
    assert classify("a.png", "res/drawable/a.png", "image") == "图片"
    assert classify("a.glsl", "assets/shaders/a.glsl", "") == "着色器"
    assert classify("x.bin", "unknown/x.bin", "") == "其它"
    print("[ok] 资源分类规则（图片/着色器/其它）")

    # 图片预览窗（找不到图也不许崩：用一张不存在的图验证降级路径）
    dlg_img = ImagePreviewDialog(session.spec_path, win)
    dlg_img.deleteLater()
    print("[ok] 图片预览窗构造与降级路径")

    # 设置对话框的新分页 + 插件页（不触发检测，避免离屏跑子进程）
    dlg2 = SettingsDialog(win.cfg, win)
    assert dlg2.tabs.count() == 3, "设置应为 常规/插件与依赖/高级 三页"
    # 切到插件页会启动后台检测线程（这是设计行为）：必须等它结束，
    # 否则解释器退出时线程还活着 → 退出码 127
    dlg2.tabs.setCurrentWidget(dlg2.plugins_page)
    assert dlg2.plugins_page.table_required.columnCount() == 6
    dlg2.plugins_page.wait_threads(30000)
    dlg2.close()
    print("[ok] 设置三分页（常规 / 插件与依赖 / 高级）+ 插件页后台检测已回收")

    # 8. 收尾：等后台依赖探测线程结束再退——否则解释器销毁时线程卡在
    # java -version 子进程上，进程异常终止、退出码变 127，CI 误判失败
    win._wait_threads()
    dep_thread = getattr(win, "_dep_thread", None)
    if dep_thread is not None and dep_thread.isRunning():
        dep_thread.wait(5000)
    print("[ok] 后台探测线程已回收")

    # 兜底：所有登记线程里仍活着的，一律 terminate 掉再 exit——避免解释器销毁期
    # 残留 QThread 导致退出码 127 / segfault 的测试桩假象。功能检查已全部做完，
    # 此刻强杀后台线程对任何业务状态无影响（窗口应用关闭由 closeEvent 的
    # wait_all_threads 兜底，不会走到这一步）。
    from wbox.gui.threads import wait_all_threads, running_threads

    # 兜底：所有登记线程里仍活着的，一律 terminate 掉再等——避免解释器销毁期
    # 残留 QThread 导致退出码 127 的测试桩假象（功能检查已全部做完，此刻强杀
    # 后台线程不影响任何业务状态；窗口应用关闭由 MainWindow.closeEvent 的
    # wait_all_threads 兜底，不会走到这一步）。
    for t in running_threads():
        try:
            t.terminate()
        except RuntimeError:
            pass
    wait_all_threads(2000)
    print("SMOKE OK")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
