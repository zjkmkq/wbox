"""白屏根因修复记录写入 spec.json：build_log log_004（runtime_fixed）。

根因（2026-10-23 真机验证发现，Saw/RE 两个工程同症）：
  module.json5 登记的是 FA 模型老字段 "routerMap": "$profile:router_map"，
  Stage 模型（API 12+）的页面登记字段是 "pages": "$profile:main_pages"。
  loadContent('pages/X') / router.pushUrl({url:'pages/X'}) 均按 pages 登记解析，
  routerMap 只服务于 pushNamedRoute 名称路由。字段缺失 → loadContent 失败 →
  主窗口无内容 → 系统默认白底（应用 startWindowBackground 为深色 #101B20，
  白屏说明页面从未挂载）→ 进程存活不闪退。RE 的"联网挂起不触发 onErrorReceive"
  同源：Web 组件从未创建，连接从未发生。
  证据链：IDE idea.log 显示进程 16 分钟存活无 faultlog；对照默认模板
  MyApplication（同时段正常运行）其打包 module.json 含 "pages":"$profile:main_pages"。
修复：Saw 与 RE 的 entry/src/main/module.json5 均将 routerMap 改为 pages
  （main_pages.json 两个工程都已正确，导航全为 url 式 pushUrl/back，无需其他改动）。
契约层纪律：只走 wbox.spec.save。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wbox import spec as wbox  # noqa: E402

AT = "2026-10-23T22:30:00+00:00"

SUMMARY = (
    "白屏根因修复（Saw/RE 同症）：module.json5 错用 FA 模型字段 "
    "\"routerMap\": \"$profile:router_map\"，Stage 模型（API 12+）页面登记字段应为 "
    "\"pages\": \"$profile:main_pages\"。loadContent/pushUrl 按 pages 解析，"
    "routerMap 仅服务 pushNamedRoute 名称路由 → loadContent 失败 → 主窗口空内容 → "
    "系统默认白底（startWindowBackground 深色 #101B20 未生效，证明页面从未挂载）→ "
    "进程存活不闪退，与真机表现完全吻合；RE 的 onErrorReceive 不触发同源（Web 从未创建）。"
    "证据：IDE idea.log 进程 16min 存活无 faultlog；对照默认模板 MyApplication "
    "module.json 为 pages 字段。修复：两工程 module.json5 routerMap→pages，"
    "main_pages.json 原本就正确，导航全为 url 式（pushUrl/back）无需改动。"
    "schema log_action 枚举新增 runtime_fixed。"
)


def main() -> None:
    data = wbox.load("spec.json")
    data["build_log"].append({
        "id": f"log_{len(data['build_log']) + 1:03d}",
        "module_id": "mod_105",
        "action": "runtime_fixed",
        "at": AT,
        "summary": SUMMARY,
        "diff_ref": "D:\\harmony\\Saw;D:\\harmony\\RE",
    })
    wbox.save(data, "spec.json")
    print(f"build_log now {len(data['build_log'])} entries (last: runtime_fixed)")


if __name__ == "__main__":
    main()
