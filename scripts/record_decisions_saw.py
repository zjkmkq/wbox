"""把圆锯模拟器的用户裁决写入 spec.json decisions 段（契约层纪律：只走 wbox.spec.save）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wbox import spec as wbox  # noqa: E402

AT = "2026-10-23T20:36:00+00:00"

DECISIONS = [
    {
        "id": "dec_001",
        "topic": "AdMob 广告（横幅+插屏）去留",
        "options": [
            "保留：鸿蒙侧接华为广告 SDK（AdsKit）",
            "去掉：单机化，无任何广告依赖",
        ],
        "chosen": "去掉，单机化",
        "reason": "单机小游戏，广告依赖会引入账号配置/合规/审核成本；去掉后工程零第三方 SDK，迁移结构最干净",
        "decided_by": "human",
        "decided_at": AT,
    },
    {
        "id": "dec_002",
        "topic": "Firebase Analytics 去留",
        "options": ["保留：找鸿蒙等价（无官方对应）", "直接弃"],
        "chosen": "直接弃",
        "reason": "单机游戏无分析诉求，鸿蒙无官方对应，弃之零成本",
        "decided_by": "human",
        "decided_at": AT,
    },
    {
        "id": "dec_003",
        "topic": "7 个位图字体（.fnt BMFont，assets/fonts/）如何渲染",
        "options": [
            "保留风格：自绘字符图集（把 png 图集 + .fnt 坐标数据搬成 ArkTS 渲染）",
            "用系统字体（HarmonyOS Sans）",
        ],
        "chosen": "用系统字体",
        "reason": "BMFont 自绘工作量大且收益低；系统字体可读性足够，省下的工程量投到玩法还原",
        "decided_by": "human",
        "decided_at": AT,
    },
    {
        "id": "dec_004",
        "topic": "玩法链确认（用户口述 vs 拆解还原）",
        "options": ["确认一致，进入画框", "有出入，先修正拆解"],
        "chosen": "确认一致：圆形锯电动→锯木板→换更好的电动圆锯→破坏更好的木板→获得更多钱",
        "reason": "用户口述与 smali 还原的完整状态机（买锯→开箱→组装→切割→4 段→结算）一致，拆解可作为拼图依据",
        "decided_by": "human",
        "decided_at": AT,
    },
]


def main() -> None:
    data = wbox.load("spec.json")
    data["decisions"] = DECISIONS
    wbox.save(data, "spec.json")
    print(f"decisions written: {len(DECISIONS)}")


if __name__ == "__main__":
    main()
