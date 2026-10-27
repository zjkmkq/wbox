"""圆锯模拟器拼图结果写入 spec.json：build_log（编译验证）+ 5 条缝记录。
契约层纪律：只走 wbox.spec.save。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wbox import spec as wbox  # noqa: E402

AT = "2026-10-23T21:40:00+00:00"

# 5 条缝：decisions 是"怎么补"的裁决，seams 是"哪里对不上"的记录，两边对应
SEAMS = [
    {
        "id": "seam_101",
        "type": "resource",
        "source": "AdMob 横幅+插屏广告（banner 布局 / 插屏时机）",
        "impact": "车间屏与游戏屏无广告位，工程零第三方 SDK",
        "fix": "去广告单机化（dec_001）；横幅布局不建，插屏时机不实现",
        "status": "verified",
        "verify_result": "编译通过：HAP 无任何广告 SDK 依赖（oh-package 依赖为空）",
    },
    {
        "id": "seam_102",
        "type": "logic",
        "source": "Firebase Analytics 埋点（onCreate/屏幕切换/切割事件）",
        "impact": "无分析上报；单机游戏无数据回流",
        "fix": "直接弃（dec_002）；assets/logs/ 已甄别为原木纹理而非日志目录（32 png 全部搬入 rawfile/logs/）",
        "status": "verified",
        "verify_result": "编译通过；资源甄别纠错：logs/ 目录实为原木 4 段切割图集",
    },
    {
        "id": "seam_103",
        "type": "resource",
        "source": "7 对 BMFont 位图字体（Quantico/bunglee/courier 等 .fnt+.png）",
        "impact": "全部文字改用系统字体（HarmonyOS Sans），失去原版字体风格",
        "fix": "用系统字体（dec_003）；图集不搬",
        "status": "verified",
        "verify_result": "编译通过：全部 Text 走系统字体，HAP 无 fonts 资源",
    },
    {
        "id": "seam_104",
        "type": "logic",
        "source": "libGDX ParticleEffect 木屑粒子（sawdust.particle 发射器参数）",
        "impact": "木屑视觉近似：Canvas 每帧喷 8~12 粒小矩形（sawdust.png 着色），发射角度/生命周期/大小不逐参数还原",
        "fix": "降级方案（dec_005）：参数简化为随机初速+重力+30~50 帧寿命",
        "status": "verified",
        "verify_result": "编译通过；粒子视觉保真度待真机确认",
    },
    {
        "id": "seam_105",
        "type": "behavior",
        "source": "切割交互：原版按住触发器→运转→每帧自动向左推进",
        "impact": "单指按住即玩；无「拖动电锯位置」增强（原版 smali 未见明确拖动定位逻辑）",
        "fix": "按拆解机制实现（dec_006）：底部触发器热区 onTouch Down/Up 驱动",
        "status": "open",
        "verify_result": "待真机：按住手感/松手停止/切断节奏需对比原版",
    },
    {
        "id": "seam_106",
        "type": "logic",
        "source": "音频 API 差异：原版 Android SoundPool/MediaPlayer → 鸿蒙 AVPlayer 新体系",
        "impact": "循环音 gas_running 用 AVPlayer.loop 属性（API 26 MediaSource 无 loop，挂 AVPlayer 实例）；一次性音效每次新建实例、stateChange 到 completed 后 release",
        "fix": "13 个 mp3 全搬 rawfile/sfx/（dec_007）；AVPlayer 池化封装于 logic/Audio.ets",
        "status": "verified",
        "verify_result": "编译通过；音画同步待真机确认",
    },
]


def main() -> None:
    data = wbox.load("spec.json")

    data["build_log"].append({
        "id": f"log_{len(data['build_log']) + 1:03d}",
        "module_id": "mod_105",
        "action": "compile_verified",
        "at": AT,
        "summary": "拼图+编译：按画框生成 D:\\harmony\\Saw 鸿蒙工程（3 页面+3 组件+3 对话框+5 logic 类+96 rawfile 资源），"
                   "hvigor assembleHap BUILD SUCCESSFUL，HAP 8,056,399 字节，三页登记入包。"
                   "修正 API 26 差异 5 类：@StorageLink 必须默认值；Stack align→alignContent；"
                   "Alignment 枚举精简（TopCenter/Left 不存在）；AVPlayer.loop 是实例属性（MediaSource 无 loop）；"
                   "ArkTS 禁 throw 任意类型/对象字面量做类型声明/计算属性名。"
                   "GamePage 每帧状态（running/progress/segmentsLeft）提升 @State 驱动 UI 刷新；"
                   "SawActor 用 @Watch 监听 props 变化控制锯片旋转。",
        "diff_ref": "D:\\harmony\\Saw",
    })

    existing = {s["id"] for s in data.get("seams", [])}
    data["seams"] = data.get("seams", []) + [s for s in SEAMS if s["id"] not in existing]
    wbox.save(data, "spec.json")
    print(f"build_log + {len(data['seams'])} seams written")


if __name__ == "__main__":
    main()
