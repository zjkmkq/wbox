"""把 Builder 探针结果登记进 spec.json（行为清单补全 + 缝记录 + build_log）。

规则：只准经 wbox.spec.save 落盘；人工记录（decisions/seams）不覆盖，只追加。
运行：& venv\\Scripts\\python.exe scripts\\record_probe.py
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wbox.spec import load, save  # noqa: E402

SPEC = ROOT / "spec.json"
BUILD_DIR = "D:\\harmony\\RE"


def main() -> int:
    spec = load(SPEC)

    # ---- 行为清单补全（来自 LOGIC.md 第 2 节，全部 disposition=confirm 待人确认）
    new_behaviors = [
        ("游戏页", "主框架加载失败（onReceivedError）",
         "显示失败遮罩「暂时无法连接游戏，请检查网络后重试。\\n账号资料不会因重试被清除。」+ 重新连接按钮"),
        ("游戏页", "HTTP 错误（onReceivedHttpError，主框架）",
         "显示失败遮罩「游戏入口暂不可用，请稍后重试。」"),
        ("游戏页", "SSL 证书错误（onReceivedSslError）",
         "取消加载 + 「连接证书验证失败，已停止加载。请联系管理员。」"),
        ("游戏页", "渲染进程崩溃（onRenderProcessGone）",
         "销毁并重建 WebView + 「游戏画面已中断，点击重新连接恢复。\\n请勿卸载应用或清除数据。」"),
        ("游戏页", "导航拦截（shouldOverrideUrlLoading + isGameUrl）",
         "非 tz.wsyt.cn:28443 的跳转一律阻止"),
        ("游戏页", "全屏视频（onShowCustomView / onHideCustomView）",
         "网页请求全屏时把自定义 View 加进根布局，退出时移除并重设沉浸式"),
        ("游戏页", "JS alert（WebChromeClient.onJsAlert）",
         "弹「游戏提示」对话框，确定/取消均回调 JsResult"),
        ("全局", "返回键（onBackPressed）",
         "弹「暂时离开游戏？」对话框：继续游戏 / 版本信息 / 返回桌面（moveTaskToBack）"),
        ("全局", "生命周期（onResume/onPause/onDestroy）",
         "onResume 重设沉浸式；onPause 暂停 WebView + flush cookie；onDestroy 关对话框 + 销毁 WebView"),
        ("全局", "WebView 不可用（createBrowser 抛 RuntimeException）",
         "「手机的 Android System WebView 不可用。\\n请在系统应用商店更新或启用后重试。」"),
    ]
    start = len(spec["behaviors"]) + 1
    for i, (screen, trigger, expected) in enumerate(new_behaviors, start):
        spec["behaviors"].append({
            "id": f"beh_{i:03d}",
            "screen": screen,
            "trigger": trigger,
            "expected": expected,
            "disposition": "confirm",
            "notes": "来自 LOGIC.md 第 2 节（smali 反编提炼）",
        })

    # ---- 缝记录（AI 已识别的差异，人工决定修复方案）
    new_seams = [
        ("behavior", "onBackPressed 返回桌面 = moveTaskToBack(true)",
         "鸿蒙无等价公开 API，「返回桌面」按钮失去原行为",
         "草案改为 toast 提示用户自行返回桌面（不 terminateSelf，保留 Web 状态）。选项：接受 / 继续寻找替代方案。待人工决定。"),
        ("behavior", "onReceivedHttpError（主框架 HTTP 错误）",
         "鸿蒙 Web 组件无对应事件，HTTP 错误只能经 onError 兜底",
         "提示文案与原版不同（onError 通用文案）。可接受则关闭，否则考虑用 onPageStart + 状态码探测补偿。"),
        ("behavior", "onReceivedSslError（证书错误取消加载）",
         "鸿蒙 Web 组件不暴露 SSL 错误回调",
         "证书失败表现为 onError 加载失败，文案与原文案不同。"),
        ("logic", "onRenderProcessGone（渲染进程崩溃恢复）",
         "鸿蒙无渲染进程概念，无法复刻「销毁重建 WebView」恢复策略",
         "草案未实现恢复逻辑，崩溃后依赖重新连接按钮。待人工评估风险。"),
        ("logic", "CookieManager.flush()（onPause 落盘 cookie）",
         "ArkTS 无等价 API，cookie 持久化由系统 Web 管理",
         "不主动 flush。对登录态的影响需真机验证。"),
        ("behavior", "screenOrientation=sensorLandscape（仅横屏）",
         "module.json5 orientation 用 auto_rotation，会允许竖屏，与原行为不一致",
         "选项：接受 / 后续用窗口 API 收紧为仅横屏。待人工决定。"),
        ("behavior", "版本信息对话框的「浏览器内核」来源",
         "原为 Chromium WebView PackageInfo 版本号，鸿蒙侧改用 controller.getUserAgent()",
         "信息内容变化，展示形式不同。"),
        ("logic", "WebSettings 映射（mixedContentMode / 媒体自动播放 / textZoom 等）",
         "对应 Web 组件属性名与枚举路径需编译期确认",
         "草案按最可能写法实现，编译报错则调整。"),
        ("behavior", "沉浸式原在 onResume/onWindowFocusChanged/onDismiss 多次重设",
         "鸿蒙侧 setWindowLayoutFullScreen 一次设置持久生效",
         "行为等价、实现不同，无用户可感知差异。已验证项，不是缺陷。"),
    ]
    seam_start = len(spec["seams"]) + 1
    for i, (stype, source, impact, fix) in enumerate(new_seams, seam_start):
        spec["seams"].append({
            "id": f"seam_{i:03d}",
            "type": stype,
            "source": source,
            "impact": impact,
            "fix": fix,
            "status": "open",
            "verify_result": "",
            "rule_update": "",
        })

    # ---- build_log：登记本次草案生成
    mod = next(m for m in spec["modules"] if m["name"] == "MainActivity")
    mod["notes"] += "；ArkTS 草案见 D:\\harmony\\RE（LOGIC.md 有完整逻辑说明与映射表），待 DevEco 编译验证"
    spec["build_log"].append({
        "id": f"log_{len(spec['build_log']) + 1:03d}",
        "module_id": mod["id"],
        "action": "draft_generated",
        "summary": (
            "AI 生成 MainActivity → ArkTS 草案（D:\\harmony\\RE）：Web 组件加载游戏 URL、"
            "沉浸式 + 常亮屏、失败遮罩、退出对话框、导航拦截、JS alert、全屏回调；"
            "逻辑说明见 LOGIC.md；新增行为 10 条、缝 9 条待人工确认"
        ),
        "diff_ref": BUILD_DIR,
        "at": datetime.now(timezone.utc).isoformat(),
    })

    save(spec, SPEC)
    print(f"spec.json 已更新：behaviors={len(spec['behaviors'])} "
          f"seams={len(spec['seams'])} build_log={len(spec['build_log'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
