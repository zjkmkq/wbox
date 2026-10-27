"""把 2026-10-22 编译验证结果登记进 spec.json（build_log + seam_008 关闭 + seam_006 文案修正）。

规则：只准经 wbox.spec.save 落盘；人工决策字段（decisions）不动。
运行：& "C:\\Users\\Administrator\\.workbuddy\\binaries\\python\\envs\\default\\Scripts\\python.exe" scripts\\record_build_result.py
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wbox.spec import load, save  # noqa: E402

SPEC = ROOT / "spec.json"
HAP = "D:\\harmony\\RE\\entry\\build\\default\\outputs\\default\\entry-default-unsigned.hap"


def main() -> int:
    spec = load(SPEC)

    # ---- build_log：编译验证通过
    mod = next(m for m in spec["modules"] if m["name"] == "MainActivity")
    mod["notes"] = mod["notes"].replace(
        "，待 DevEco 编译验证",
        "；2026-10-22 命令行 hvigor assembleHap 编译通过（SDK 26 / API 26，"
        "BUILD SUCCESSFUL，HAP 120,491 字节，Index 页经 routerMap 登记入包）",
    )
    spec["build_log"].append({
        "id": f"log_{len(spec['build_log']) + 1:03d}",
        "module_id": mod["id"],
        "action": "compile_verified",
        "summary": (
            "DevEco 命令行编译验证通过：hvigor assembleHap BUILD SUCCESSFUL"
            "（SDK 26/API 26，33 tasks，HAP 产物 120,491 字节）。"
            "修正高风险 API 8 处（均依据 SDK d.ts 核实）：webview 导入 @kit.ArkUI→@kit.ArkWeb；"
            "layoutWidth/Height→width()/height()；mixedContentMode→mixedMode(MixedMode.All)；"
            "onPageStart→onPageBegin；onError→onErrorReceive；"
            "event.dataRequest→event.data；onAlert 回调须返回 boolean；"
            "promptAction.showDialog/showToast（API 18 弃用）→getUIContext().getPromptAction()，"
            "setKeepScreenOn（API 9 弃用）→setWindowKeepScreenOn。"
            "另修复 ArkTS 规则 arkts-no-any-unknown（Promise .catch 回调参数须显式标注类型）"
            "与 app_name 重复声明（entry 副本删除，保留 AppScope 声明）。"
            "产物：" + HAP
        ),
        "diff_ref": "D:\\harmony\\RE",
        "at": datetime.now(timezone.utc).isoformat(),
    })

    # ---- seam_008（WebSettings 属性名）：编译期确认完毕，verified
    seam8 = next(s for s in spec["seams"] if s["id"] == "seam_008")
    seam8["status"] = "verified"
    seam8["verify_result"] = (
        "2026-10-22 编译通过，最终映射：MIXED_CONTENT_ALWAYS_ALLOW→mixedMode(MixedMode.All)"
        "（MixedMode 为 declare enum 全局枚举）；DOM Storage→domStorageAccess(true)；"
        "onPageStarted→onPageBegin；onReceivedError→onErrorReceive；"
        "onJsAlert→onAlert（返回 true 自消费，event.result.handleConfirm()）。"
        "媒体自动播放/宽视口/textZoom 等鸿蒙侧有对应属性，草案未逐一设置（见 behaviors 人工确认）。"
    )
    seam8["rule_update"] = (
        "迁移规则：API 26 下 Web 事件名以 SDK d.ts（openharmony/ets/component/web.d.ts）为准，"
        "不用 API 12 以前的旧名；枚举优先用全局 declare enum；"
        "promptAction 全局函数自 API 18 弃用，一律走 getUIContext().getPromptAction()。"
    )

    # ---- seam_006（横屏）：module.json5 最终未设 orientation 字段，修正 impact 文案
    seam6 = next(s for s in spec["seams"] if s["id"] == "seam_006")
    seam6["impact"] = (
        "鸿蒙 module.json5 未设 orientation 字段，跟随系统旋转策略（默认允许竖屏），"
        "与原 sensorLandscape 仅横屏不一致"
    )

    save(spec, SPEC)
    print(f"spec.json 已更新：build_log={len(spec['build_log'])} "
          f"seams closed={sum(1 for s in spec['seams'] if s['status'] == 'closed')}/{len(spec['seams'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
