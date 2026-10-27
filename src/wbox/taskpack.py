"""wbox.taskpack —— 阶段 4「填上」的任务包导出：把上下文装成一包，粘给任意 AI。

定位（写死，不许绕）：
- 解决"每次聊半天"：应用一键导出 上下文包（spec + 提案 + 关键 smali +
  方法论 + 指令模板），用户粘给任意 AI（含本工作台聊天窗），拿回的 ArkTS
  文件按提案目标路径落盘。API 直连不可用时这条路永远可用。
- 方法论（METHODOLOGY.md）是固化资产：参照重做、数值原样搬、API 26 差异、
  ArkTS 禁则、缝记录规范——全部来自圆锯/RE 两个真实项目的验证结论。
- 导出物只读，不改 spec；落盘由调用方（GUI）经 wbox.spec 走契约层。

CLI：
    python -m wbox.taskpack spec.json -o exports/taskpack
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from wbox.plan import generate_proposal
from wbox.spec import load

# ---------------------------------------------------------------- 方法论（固化资产）

METHODOLOGY = """# 白盒迁移方法论（WBox 固化版 v1）

> 本文件是跨平台迁移的"裁判规则"。你（AI）是执行者，人类是决策者。
> 核心原则：**参照重做，不逐行翻译**。原应用只提供三类参考——资源、逻辑、行为；
> 鸿蒙侧按鸿蒙的方式重新实现，所有"对不上"显式登记为缝（seam），不藏着掖着。

## 1. 数值与公式铁律

- 游戏数值（价格、速度、系数、奖励公式、判定阈值）**从 smali 常数原样搬运**，
  一个数字都不许"顺手调整"。调整必须经人工决策（decisions），且写明理由。
- 单位换算（dp/vp、sp/fp）按鸿蒙官方换算表，换算过程写进 notes。
- 网格化表达：能用整数网格表达的数值（如射程 120 = 6 格）必须网格化。

## 2. 代码生成规范（ArkTS / HarmonyOS NEXT）

- 每文件结构：顶部注释块（原版对应类/方法 + 迁移说明）→ import → 常量 →
  类型/接口 → 类/结构体 → 导出。@Entry 页面配 @Builder 导出函数。
- 共享状态：AppStorage 中央状态 + @StorageLink/@StorageProp；@StorageLink
  **必须给默认值**，否则运行报错。
- 每帧变化的状态必须 @State 才驱动 UI 刷新；高频粒子用命令式 Canvas，禁止
  每帧重建组件树。
- 禁则：throw 只接受 Error 子类；对象字面量不能做类型声明（回调参数用
  interface）；禁计算属性名；ForEach 回调参数禁对象字面量类型。
- 布局：Stack 用 alignContent（无 align 参数）；Alignment 枚举已精简
  （无 TopCenter/Left，用 Top/Start 等组合）。
- 音频：AVPlayer 新体系 = createAVPlayer + createMediaSourceWithFd
  ({fd, offset, length}) + setMediaSource + prepare + play；loop 是
  **实例属性**；一次性音效每次新建实例，监听 stateChange 到 'completed'
  后 release。
- 页面登记（白屏头号根因）：module.json5 写 `"pages": "$profile:main_pages"`；
  routerMap 是 FA 老字段只服务 pushNamedRoute。loadContent/pushUrl 按 pages 解析。
- Web 组件：mixedMode(MixedMode.All)；事件用 onPageBegin/onErrorReceive/
  onLoadIntercept；拦截字段 event.data.getRequestUrl()。

## 3. 单机化默认策略（除非人工另有决策）

- 广告 SDK（AdMob/Unity Ads 等）：**不迁移**，工程零第三方依赖。
- Firebase/统计/登录：**不迁移**。
- 位图字体：改用系统字体，不搬字体文件。
- 权限：只申请确实用到的（如震动），不照搬原 manifest。

## 4. 输出格式约定（必须遵守，否则无法自动落盘）

按提案中的目标路径，逐文件输出，格式：

```ets
// FILE: pages/GamePage.ets
<文件完整内容>
```

- 一个文件一段，FILE 行必须与提案 target 完全一致。
- 资源文件不输出内容（已在提案 resource_moves 里列明搬迁路径），只输出代码文件。
- 模块间依赖只许 import 提案内的目标路径，不许发明新路径。

## 5. 缝（seam）登记规范

每个"对不上"的点都要登记：source（原版行为）/ impact（鸿蒙侧影响）/
fix（怎么补）/ status（open→fixed→verified）。人工逐条验收后才许 verified。
"""

PROMPT_TEMPLATE = """# 任务：按提案生成鸿蒙 ArkTS 草案工程

你是白盒迁移执行者。下面是原应用的拆解结果与鸿蒙结构提案。
请严格按《methodology.md》的规则与输出格式，把提案中的 logic_classes 与
ui_units 逐文件生成为 ArkTS 代码。

## 原应用概况

- 应用：{app_name}
- 源 APK：{apk_source}
- 清单规模：资源 {n_res} 条 / 模块 {n_mod} 个 / 行为 {n_beh} 条
{web_shell_note}
## 鸿蒙结构提案（人工已确认的映射，目标路径以此为准）

### 逻辑类/页面/组件划分
{logic_table}

### UI 单元（按屏归并的行为）
{ui_table}

### 资源搬迁（节选 migrate 项，前 80 条）
{res_table}

### 本次人工决策（必须遵守）
{decisions}

### 待你提示人工的开放问题（不要在代码里擅自决定）
{questions}

## 关键 smali 参考

以下文件已从原包解出，与提案模块一一对应。数值与公式以这些文件为准：
{smali_list}

## 输出要求

1. 按 methodology.md 第 4 节的 FILE 格式逐文件输出。
2. 先输出模块依赖最少的文件（logic 层 → 组件层 → 页面层）。
3. 遇到提案没覆盖但原版确实有的行为：不要自行发挥，列入"建议补充的缝"清单
   放在输出末尾。
4. 全部输出完后，附一段"映射核对表"：每个提案 target → 已输出/未输出及原因。
"""

README = """# WBox 任务包使用说明

这个包是「填上」步的上下文。两种用法：

## 用法 A：粘给任意 AI（无需 API key）

1. 把本目录下的 `prompt.md` + `methodology.md` + `spec.json` + `smali/`
   一起发给任意大模型（本工作台聊天窗、网页版均可）。
2. 拿回的文件按 prompt 里的 FILE 路径，落盘到工程 `draft/` 目录
   （WBox 的「填上」页有"粘贴导入"按钮可代劳）。
3. 回到「补缝」步编译验证。

## 用法 B：应用内 API 直连

在「填上」页配置 base_url + key + model 后一键生成（内容与本包一致）。

## 目录说明

- prompt.md      给 AI 的指令（已填入本工程上下文）
- methodology.md 迁移方法论（裁判规则）
- spec.json      契约副本（三段清单 + 决策）
- smali/         提案相关的关键 smali 文件
"""


# ---------------------------------------------------------------- 渲染


def _render_logic_table(logic_classes: list[dict]) -> str:
    lines = ["| 逻辑类 | 原版引用 | 目标文件 | 模式 | smali 参考 |", "|---|---|---|---|---|"]
    for c in logic_classes:
        smali = c.get("smali", "")
        ref = f"`smali/{smali}.smali`" if smali else "—"
        lines.append(f"| {c['name']} | {c['mod_id']} | `{c['target']}` | {c['pattern']} | {ref} |")
    return "\n".join(lines)


def _render_ui_table(ui_units: list[dict]) -> str:
    lines = ["| 屏 | 类型 | 目标文件 | 行为数 |", "|---|---|---|---|"]
    for u in ui_units:
        lines.append(f"| {u['screen']} | {u['kind']} | `{u['target']}` | {len(u['beh_ids'])} |")
    return "\n".join(lines)


def _render_res_table(moves: list[dict], limit: int = 80) -> str:
    mig = [m for m in moves if m["action"] == "migrate"][:limit]
    lines = ["| 资源 | 目标路径 |", "|---|---|"]
    for m in mig:
        lines.append(f"| {m['name']} | `{m['target']}` |")
    return "\n".join(lines)


def _render_decisions(decisions: list[dict]) -> str:
    if not decisions:
        return "（无人工决策）"
    return "\n".join(f"- **{d.get('topic')}** → {d.get('chosen')}（理由：{d.get('reason', '')}）"
                     for d in decisions)


def _render_questions(questions: list[dict]) -> str:
    if not questions:
        return "（无）"
    return "\n".join(f"- {q.get('topic')}（{q.get('why', '')}）" for q in questions)


def _render_web_shell_note(proposal: dict) -> str:
    """Web 壳工程的强约束横幅。

    没有这段，AI 会把提案外的 Capacitor/Cordova 框架类也一并"补全"——2026-10-26
    跳石子工程就是这么产出 141 个文件的（其中 134 个框架类，靠删一行
    layoutDirection 幻觉调用才编过）。横幅要写死"只生成列出的文件"。
    """
    if not proposal.get("web_shell"):
        return ""
    return """
## ⚠ 这是 Web 壳工程（Capacitor/Cordova），游戏本体是 H5

原版把 Vite/Webpack 产物铺在 `assets/public/` 下，原生层只是一个 WebView 宿主
Activity。因此：

1. **只生成下面提案表格里列出的文件，一个都不要多**。Capacitor/Cordova 框架类
   （Bridge/Plugin/JSObject/CordovaInterface/…ExternalSyntheticLambda* 等）一律
   **不生成、不搬运、不占位**——它们是安卓 WebView 外壳，鸿蒙侧由 ArkWeb 的
   `Web` 组件 + `javaScriptProxy` 承担。
2. 容器页用 `Web({ src: $rawfile('index.html'), controller })` 承载 H5，
   `.domStorageAccess(true)` 开 localStorage 存档。
3. H5 在 ArkWeb 里拿不到 `androidBridge` / `webkit.messageHandlers.bridge`，
   即 `isNativePlatform() === false`，会**自动走 web 降级**（Preferences→
   localStorage、Haptics→navigator.vibrate、IAP→mock）。**不要伪造原生桥**，
   只补缺失的 `navigator.vibrate` → 原生 vibrator。
4. `assets/public/` 整树已按原相对路径搬进 rawfile（`./assets/...` 不断链）；
   `index.html` 里的 `crossorigin` 属性会因 resource:// 不透明源导致整包白屏，
   装配器会自动去除，你不要再手动改。

"""


def _collect_smali(spec: dict, work_dir: Path, out_dir: Path) -> list[str]:
    """把提案逻辑类对应的 smali 复制进任务包；返回相对路径清单。

    路径直接取提案条目的 smali 字段（plan 生成时推断，覆盖顶层类、
    内部类、混淆短包类）。**按包路径原样落盘**——混淆工程里
    w0/a.smali、b1/a.smali、y0/a.smali 同名类一片，平铺会互相覆盖，
    最后只剩一个 a.smali，任务包直接失去参考价值。
    找不到的条目跳过（外部库类无参考价值）。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    proposal = spec.get("proposal") or generate_proposal(spec)
    # smali 根：work/<apk-stem>/smali*；先建索引，避免每条逻辑类 rglob 全树
    roots = sorted(work_dir.glob("*/smali*")) or sorted(work_dir.glob("smali*"))
    index: dict[str, Path] = {}
    for root in roots:
        for f in root.rglob("*.smali"):
            key = f.relative_to(root).as_posix()[:-len(".smali")]
            index.setdefault(key, f)
    copied: list[str] = []
    seen: set[str] = set()
    for c in proposal.get("logic_classes", []):
        rel = str(c.get("smali", ""))
        if not rel or rel in seen:
            continue
        found = index.get(rel)
        if not found:
            continue
        dest = out_dir / f"{rel}.smali"
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(found, dest)
            copied.append(f"smali/{rel}.smali")
            seen.add(rel)
        except OSError:
            pass
    return copied


# ---------------------------------------------------------------- 主入口


def render_prompt(spec: dict, smali_list: list[str]) -> str:
    """渲染给 AI 的指令（任务包与 API 直连共用，保证内容一致）。"""
    proposal = spec.get("proposal") or generate_proposal(spec)
    return PROMPT_TEMPLATE.format(
        app_name=spec.get("project", {}).get("name", ""),
        apk_source=spec.get("project", {}).get("source", ""),
        n_res=len(spec.get("resources", [])),
        n_mod=len(spec.get("modules", [])),
        n_beh=len(spec.get("behaviors", [])),
        logic_table=_render_logic_table(proposal.get("logic_classes", [])),
        ui_table=_render_ui_table(proposal.get("ui_units", [])),
        res_table=_render_res_table(proposal.get("resource_moves", [])),
        decisions=_render_decisions(spec.get("decisions", [])),
        questions=_render_questions(proposal.get("open_questions", [])),
        web_shell_note=_render_web_shell_note(proposal),
        smali_list="\n".join(f"- `{s}`" for s in smali_list) or "（未找到对应 smali，请从 work/ 目录手动补充）",
    )


def build_taskpack(spec_path: str | Path, out_dir: str | Path) -> Path:
    """生成任务包目录，返回路径。"""
    spec_path = Path(spec_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    spec = load(spec_path)

    # 1. 方法论 + 说明（newline="\n" 锁定 LF，防 Windows CRLF）
    (out / "methodology.md").write_text(METHODOLOGY, encoding="utf-8", newline="\n")
    (out / "README.md").write_text(README, encoding="utf-8", newline="\n")
    (out / "spec.json").write_text(
        __import__("json").dumps(spec, ensure_ascii=False, indent=2),
        encoding="utf-8", newline="\n")

    # 2. smali 参考（先清旧 smali/——重导出时旧平铺文件会残留，
    # 与按包路径的新文件混在一起误导 AI；本目录由任务包独占拥有）
    smali_dir = out / "smali"
    if smali_dir.exists():
        shutil.rmtree(smali_dir, ignore_errors=True)
    work_dir = spec_path.parent / "work"
    smali_list = _collect_smali(spec, work_dir, smali_dir)

    # 3. prompt
    (out / "prompt.md").write_text(render_prompt(spec, smali_list), encoding="utf-8", newline="\n")
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="填上：导出上下文任务包")
    parser.add_argument("spec", help="spec.json 路径")
    parser.add_argument("-o", "--out", required=True, help="输出目录")
    args = parser.parse_args(argv)
    out = build_taskpack(args.spec, args.out)
    files = sorted(p.name for p in out.rglob("*") if p.is_file())
    print(f"任务包已生成：{out}")
    for f in files:
        print(" -", f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
