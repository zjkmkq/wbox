"""把圆锯模拟器深挖结果写入 spec.json（经 wbox.spec.save 契约层落盘）。

深挖来源：work/saw 解包目录的 smali（混淆后包名 w0/b1/a1/x0/z0/d1/c1/y0/g4/h4）。
自动提取层只给出 manifest 级浅层信息；本脚本把代码级结构补进 modules/behaviors。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wbox.spec import load, save  # noqa: E402

spec = load(Path("spec.json"))

# ---- modules：代码级真实结构（混淆类名 → 语义角色）----
deep_modules = [
    {
        "id": "mod_101",
        "name": "AndroidLauncher（Android 入口）",
        "source_ref": "com.dim.circularsaw.AndroidLauncher",
        "disposition": "confirm",
        "notes": "libGDX AndroidApplication 子类；沉浸式模式 + 2x MSAA；RelativeLayout 包 GLView + AdMob 横幅（大屏才显示）+ 插屏广告；Firebase Analytics；横屏锁定",
    },
    {
        "id": "mod_102",
        "name": "w0/g（ApplicationListener 根）",
        "source_ref": "w0/g.smali",
        "disposition": "confirm",
        "notes": "ApplicationAdapter + InputProcessor；create() 建 w0/c(Game) + h4/a；AppStatePreferences 读档/存根；pause 存 resume 读",
    },
    {
        "id": "mod_103",
        "name": "w0/c（Game 主控 + 屏幕路由）",
        "source_ref": "w0/c.smali",
        "disposition": "confirm",
        "notes": "3 屏幕：b1/d 加载屏→b1/b 车间屏→b1/a 游戏屏；持 3 电锯(a1/a,b,c)、8 锯片(x0/b)、6 原木(z0/b)、状态 w0/e；ExtendViewport(12.8,7.2,19.2,10.8)；资产加载完 + 3.5s 后才进车间屏",
    },
    {
        "id": "mod_104",
        "name": "b1/b（车间/选购屏）",
        "source_ref": "b1/b.smali",
        "disposition": "confirm",
        "notes": "电锯位两个槽(当前/下一个) + 左右箭头切换 + 购买(钱够则扣分款解锁并进场,不够则 locked 音+抖动) + 振动开关 + 金额显示；点击已解锁电锯→g(id) 进入游戏屏",
    },
    {
        "id": "mod_105",
        "name": "b1/a（切割游戏屏）",
        "source_ref": "b1/a.smali",
        "disposition": "confirm",
        "notes": "持 w0/h 电锯演员、d1/b 原木、w0/i HUD、w0/f 粒子/提示；render 驱动切割进度→完成结算(加分/金币喷泉/标语/每 7 根弹结算窗)；触摸拖动电锯",
    },
    {
        "id": "mod_106",
        "name": "w0/h（电锯演员 + 点火状态机）",
        "source_ref": "w0/h.smali",
        "disposition": "confirm",
        "notes": "Group：机身 h$g(影子+木屑粒子)/锯片 h$h(旋转)/主轴/背板/触发器 h$i；生命周期 木箱→开箱(i(Z))→组装(w())→可玩；按住触发器=运转(starting→running 音+振动)，松手停止；act() 里执行切割位移",
    },
    {
        "id": "mod_107",
        "name": "d1/b（原木：4 段切割 + 奖励）",
        "source_ref": "d1/b.smali",
        "disposition": "confirm",
        "notes": "原木=4 个分段演员(woodlog-lX-1..4)；进度=锯片横向深入度；每段切断飞落(0,-7,2s)；切断数 m()；奖励 q()=硬度×等级×40,全断再×4",
    },
    {
        "id": "mod_108",
        "name": "实体数据：3 电锯 / 8 锯片 / 6 原木",
        "source_ref": "a1/a,b,c + x0/a,b + z0/a,b",
        "disposition": "confirm",
        "notes": "电锯 m1 免费/m2 715/m3 1200(e=0.3/0.4/0.5 机型速度)；锯片 m1-m8 价格 0/120/140/165/230/170/220/150(d=价格/350 切割系数,m1=0.3)；原木 l1-l6 硬度 0.25/0.35/0.5 × 等级 1/2，木种 Pine/Elm/Mahogany",
    },
    {
        "id": "mod_109",
        "name": "w0/e（全局状态）+ w0/g 存档",
        "source_ref": "w0/e.smali",
        "disposition": "confirm",
        "notes": "score 金额 / logsCompleted 完成根数 / vibration / 4 个 FTUE 提示旗标 / 切割进度 b / 切割中 a；Preferences 键: score,logsCompleted,vibration,saw-{id}-{unlocked,constructed,unboxed,blade},blade-{id}-locked,ftue*",
    },
    {
        "id": "mod_110",
        "name": "UI 组件层",
        "source_ref": "w0/i + c1/* + y0/* + g4/*",
        "disposition": "confirm",
        "notes": "w0/i HUD(返回/选木/选锯片+金额+油量表)；c1/b 电锯槽/ c1/c 指示器/ c1/d 金额框/ c1/a 油量表；y0/a 选锯片对话框(可购买)/ y0/b 选原木对话框(3列网格)/ y0/c 结算窗(rays+coins)；g4/a 资产注册表(136 键)",
    },
    {
        "id": "mod_111",
        "name": "w0/f（粒子 + FTUE 提示）",
        "source_ref": "w0/f.smali",
        "disposition": "confirm",
        "notes": "木屑粒子(particle/sawdust.particle)挂演员；首次提示: Touch to unbox / Touch to build / Select a wood log + help-arrow",
    },
]

existing = {m["id"] for m in spec["modules"]}
spec["modules"].extend(m for m in deep_modules if m["id"] not in existing)

# ---- behaviors：代码级玩法行为（screen=所在界面, disposition=confirm 待人判）----
deep_behaviors = [
    {
        "id": "beh_101",
        "screen": "车间屏",
        "trigger": "车间屏点击电锯槽",
        "expected": "已解锁→进场(click 音+切到游戏屏)；未解锁且钱够→扣款+解锁(saw-unlocked 音)+进场；钱不够→saw-locked 音+槽位抖动",
        "disposition": "confirm",
    },
    {
        "id": "beh_102",
        "screen": "游戏屏",
        "trigger": "游戏屏设置电锯时(s(La1/d))",
        "expected": "未开箱→显示木箱(wooden-box),点击开箱(move-box 音)；已开箱未组装→显示背板+进入组装动画(锯片/主轴/整机三段 moveTo 定时 0.8/1.9/2.6s,socket_wrench 音)；已组装→可切割",
        "disposition": "confirm",
    },
    {
        "id": "beh_103",
        "screen": "游戏屏",
        "trigger": "游戏中按住电锯触发器(w0/h$i 热区)",
        "expected": "点火(starting 音)→运转(gas_running 循环音+振动[0,200]ms+木屑粒子)；松手/失焦→停止(stopping 音)；运转时每帧向左位移,位移量=锯片系数×机型速度×2.5/(原木等级×硬度)×dt",
        "disposition": "confirm",
    },
    {
        "id": "beh_104",
        "screen": "游戏屏",
        "trigger": "切割进度满一段(g()==1.0)",
        "expected": "当前段飞落(0,-7,2s)；段索引 d--；切断 1/2/3 段时显示 30%/60%/90% done!；锯机归位(park)1s 后继续",
        "disposition": "confirm",
    },
    {
        "id": "beh_105",
        "screen": "游戏屏",
        "trigger": "第 4 段切断(d==0)",
        "expected": "加分=硬度×等级×40×4(整根倍率)；logsCompleted++；金币喷泉(5 币错时动画)+随机标语(Well done!/Perfect!/Amazing!)；每满 7 根→1.5s 后弹 welldone 结算窗(log-completed 音)；否则 1s 后上下一根",
        "disposition": "confirm",
    },
    {
        "id": "beh_106",
        "screen": "游戏屏",
        "trigger": "游戏屏点 blade-select-button",
        "expected": "y0/a 对话框列出 8 锯片+价格；已装备→选中(click)；未解锁且钱够→购买(blade-unlocked 收银音)+装备；钱不够→blade-locked 音",
        "disposition": "confirm",
    },
    {
        "id": "beh_107",
        "screen": "游戏屏",
        "trigger": "游戏屏点 log-select-button",
        "expected": "y0/b 对话框 3 列网格列出 6 原木(woodlog-lX-menu 图标)；选中→d1/b.t(log) 重载 4 段图+切割线",
        "disposition": "confirm",
    },
    {
        "id": "beh_108",
        "screen": "游戏屏",
        "trigger": "对应状态首次出现",
        "expected": "未开箱 Touch to unbox / 未组装 Touch to build / 无原木 Select a wood log,help-arrow 指向目标,旗标持久化",
        "disposition": "confirm",
    },
    {
        "id": "beh_109",
        "screen": "车间屏",
        "trigger": "车间屏振动开关",
        "expected": "vibration 布尔持久化；切割中开启则周期性振动",
        "disposition": "confirm",
    },
]

existing_b = {b["id"] for b in spec["behaviors"]}
spec["behaviors"].extend(b for b in deep_behaviors if b["id"] not in existing_b)

# ---- build_log：记录深挖（module_id 挂到游戏主控模块）----
spec["build_log"].append(
    {
        "id": f"log_{len(spec['build_log']) + 1:03d}",
        "module_id": "mod_103",
        "action": "extracted",
        "at": "2026-10-23T00:00:00+00:00",
        "summary": "smali 深挖：还原 libGDX 游戏完整结构(3 屏/3 锯/8 片/6 木/切割公式/经济数值),写入 mod_101-111 + beh_101-109",
        "diff_ref": "work/saw",
    }
)

save(spec, Path("spec.json"))
print("spec.json enriched: modules", len(spec["modules"]), "behaviors", len(spec["behaviors"]))
