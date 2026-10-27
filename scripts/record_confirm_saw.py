"""白屏修复真机复验结果写入 spec.json：build_log log_005（confirmed）。
用户 2026-10-23 22:54 确认：IDE Run 后应用正常渲染，白屏病根清除。
契约层纪律：只走 wbox.spec.save。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wbox import spec as wbox  # noqa: E402

AT = "2026-10-23T22:55:00+00:00"

SUMMARY = (
    "白屏修复真机复验通过（用户确认）：Saw 工程 IDE Run 后正常渲染，白屏病根清除。"
    "根因回顾：module.json5 错用 FA 字段 routerMap（Stage 模型应为 pages）导致 "
    "loadContent 失败、页面不挂载。一行修复（routerMap→pages）同时惠及 RE 工程。"
    "遗留：seam_105 切割交互手感（按住/松手/切断节奏/音画同步）仍需完整玩法验收。"
)


def main() -> None:
    data = wbox.load("spec.json")
    data["build_log"].append({
        "id": f"log_{len(data['build_log']) + 1:03d}",
        "module_id": "mod_105",
        "action": "confirmed",
        "at": AT,
        "summary": SUMMARY,
        "diff_ref": "D://harmony//Saw;D://harmony//RE",
    })
    wbox.save(data, "spec.json")
    print(f"build_log now {len(data['build_log'])} entries (last: confirmed)")


if __name__ == "__main__":
    main()
