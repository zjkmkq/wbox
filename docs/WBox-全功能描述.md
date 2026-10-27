# 跨平台迁移白盒工作台 WBox —— 全功能详细描述

> 版本基线：2026-10-25（v0.2.0，PyInstaller 单文件分发）
> 本文档描述与 `src/wbox/` 源码实现一一对应，不含未建成功能（未建成项在末章明确标注）。

---

## 1. 一句话定位

**WBox 是一个本地桌面应用，把 Android 应用白盒迁移成 HarmonyOS NEXT 工程：自动拆解原应用 → 生成结构提案 → 人工裁决 → AI 辅助重写 ArkTS → 自动装配成可编译工程 → 命令行编译验证，全过程留痕可回溯。**

## 2. 解决什么问题

把 Android 应用迁到鸿蒙，行业现状是三条死路：

| 路线 | 问题 |
|---|---|
| 逐行翻译 Java/Kotlin → ArkTS | 鸿蒙没有 Android 的运行时，翻译出来的代码跑不起来，白费人力 |
| 用在线"一键转换"服务 | 黑盒、不可控、应用要上传到别人服务器，商业资产泄露 |
| 从零重写 | 没有原应用细节参照，玩法/数值/资源全靠猜，做出来不像 |

WBox 走第四条路：**参照重做**。原应用被拆成资源、逻辑、行为三类参考，鸿蒙侧对着参考重新做，差异（缝）被显式记录、逐条验证。AI 是副驾驶负责搬重物，人保留判断权——契约层 `decided_by` 恒为 `human`。

## 3. 核心设计哲学（写死在代码里的四条铁律）

1. **契约唯一纽带**：整个工作台只有一个数据文件 `spec.json`（迁移契约），所有模块只准通过 `wbox.spec` 契约层读写，禁止各自 `json.load`。契约经 `spec.schema.json` 严格校验（`additionalProperties=false`，多一个字段都不收）。
2. **版本化迁移链**：`spec_version` 与代码 `SPEC_VERSION` 不符时走注册的迁移链逐版升级，禁止手改文件。保存为原子写（临时文件 + `os.replace`），崩溃不留半个文件。
3. **参照重做，不逐行翻译**：AI 拿到的指令模板（METHODOLOGY）固化了两个真实项目的验证结论——数值原样搬、API 26 差异、ArkTS 禁则、缝记录规范。
4. **工程落地优先**：所有数值精确（如射程 120 = 6 格），拒绝引擎实现不了的功能，产物必须过真编译，不以"看起来对"交差。

## 4. 功能总览：五步流水线

```
APK ──①拆──▶ spec 三段清单 ──②画拼图──▶ 结构提案 ──③判断──▶ 人工决策
                                                              │
HAP ◀──⑤补缝── 可编译鸿蒙工程 ◀──装配器── draft/ ArkTS ◀──④填上──┘
                    │                                        ▲
                    └── hvigor 流式编译 ◀── 编译记录/缝状态板  三通道（任务包/API/粘贴）
```

每一步在 GUI 里是一个页面，在 CLI 里是一个模块（`python -m wbox.extract` 等），两层共用同一契约层。

---

## 5. 分步功能详述

### ① 拆（wbox.extract + GUI extract_step）

**做什么**：apktool 流式解包 APK → 产出机器可推导的三段清单，写进 spec。

- **资源清单**：`res/` 与 `assets/` 全量文件登记（名称/类型/密度/路径），图标密度变体自动合并，`public.xml` 等 apktool 产物正确跳过
- **模块骨架**：从 manifest 提取 Activity / Application 入口；入口可达的自有代码与库代码分离（manifest 入口 → smali 类型引用 BFS 闭包 → 自有包判定），圆锯工程实测量化：入口可达自有 132 类 / 库及不可达 8932 类
- **行为骨架**：从 LAUNCHER intent-filter 等提取行为条目（打开应用 → 进入哪个 Activity）
- **GUI 实跑**：worker 线程跑 apktool，日志逐行实时进界面；重复提取不毁人工记录（`--force` 时保留 decisions/seams，build_log 追加不清空）
- **职责边界**：只搬机器可推导的事实，逻辑细节不在这里猜

### ② 画拼图（wbox.plan + GUI plan_step）

**做什么**：把 spec 三段清单转成鸿蒙结构的初稿提案，供人工逐条改。

- **确定性启发式映射**（纯本地、毫秒级）：资源 → rawfile 搬迁表；模块 → logic 类 / 页面 / 组件划分；行为 → 页面/组件/对话框归并
- **库资源过滤**（补 extract 的已知缺陷）：AndroidX/Material/Firebase/广告 SDK 模板噪音打上 drop 理由，不淹没游戏自有资产
- **三张可编辑表**：资源搬迁表 / 逻辑类表 / UI 单元表——action 下拉、target 手改、reason 只读；编辑即存（原子写），主窗左右栏实时联动
- **待裁决列表**：提案自动产出的开放问题，送 ③ 步人工裁决
- **圆锯工程实测量化**：迁移 102 项 / 弃用 400 项 / 逻辑类 11 / UI 单元 3 / 待裁决 3

### ③ 判断（GUI decide_step）

**做什么**：开放问题逐条人工裁决，写进 spec.decisions。

- 选中问题 → 填结论（+可选理由）→ 记录决策
- `id` 自增、`decided_by` 恒为 `human`、`decided_at` 当前 UTC——**判断权永远在人**
- 同一问题重复裁决追加新决策，旧的不删，契约可回溯
- 圆锯工程已有 7 条人工决策在案

### ④ 填上（wbox.taskpack / aiclient / draft + GUI fill_step）

**做什么**：按提案生成 ArkTS 草案，落 `draft/` 目录。三个通道，产物统一走 `wbox.draft` 落盘：

| 通道 | 机制 | 适用 |
|---|---|---|
| A 任务包导出 | 一键导出上下文包（spec + 提案 + 关键 smali + 方法论 + 指令模板）到 `exports/`，整个粘给任意 AI | 没有 API key；用网页版 AI |
| B API 直连 | OpenAI 兼容 `/chat/completions`，流式 SSE 逐段回调，不绑定厂商；key 只从本地配置读，不落日志不进任务包 | 配了 DeepSeek 等兼容端点 |
| C 粘贴导入 | 把别处 AI 的输出粘进来，解析 FILE 段落盘 | 混合使用 |

- **落盘安全规则**：只接受相对路径，拒绝对盘符/UNC/`..` 越界/空路径；不覆盖 spec.json（契约不走本通道）
- **交付契约**：AI 产出为标准 FILE 格式（首行 `// FILE: 路径` + ```ets 块），`exports/ai_output.md` 可直接粘贴回填
- 落盘成功写 `spec.build_log`（action=draft_generated），自动提示回 ⑤ 步编译

### ⑤ 补缝（wbox.hvigor / wbox.assemble + GUI seal_step）

**做什么**：把 draft/ + 资源 + 骨架模板装配成可编译鸿蒙工程，跑 hvigor 编译验证，管理缝状态。

- **自动装配**（消灭最大手工断点）：AppScope/build-profile/module.json5/hvigorfile/EntryAbility/main_pages 一次装齐；页面登记从 draft 产物反推（@Entry 结构体），不靠可能过期的提案猜
- **模板铁律内置**：`module.json5` 写 `"pages": "$profile:main_pages"`（Stage 模型；FA 的 routerMap 错用即白屏，两个真实工程同症根因已修）；SDK 版本由 `hvigor.sync_sdk_versions` 对齐工具链
- **流式编译**：子进程跑 assembleHap，日志逐行进界面；unsigned HAP 是正常的（签名归 DevEco IDE），只报 BUILD SUCCESSFUL/FAILED 与产物路径
- **缝状态板**：五类缝（logic 逻辑 / resource 资源 / behavior 行为 / ecosystem 生态 / data 数据）全量呈现，状态四档（待补/已修待验/已验证/不处理）+ 验证结果列，编辑即存；**行为缝必须真机对比后才允许标 verified**（界面常驻提示）
- **编译记录**：build_log 时间线（时间/动作/摘要/产物路径），compile_verified 与 runtime_fixed 分别入档
- **任务完成自动关机**（可选）：设置开启后编译出 HAP 弹 60 秒倒计时，立即关机/取消均可

---

## 6. 底层支撑系统

### 6.1 spec.json 契约层（wbox.spec）

八个顶层字段：`spec_version / project / resources / modules / behaviors / decisions / build_log / seams / proposal`。工程目录即一个 `.wbox` 目录，spec.json 是唯一事实源；schema 严格校验 + 版本迁移链 + 原子写 + 自动刷新 `updated_at`。

### 6.2 工作区与存储体系（wbox.config，2026-10-25 产品化）

**应用本身拥有一个集中文件夹**，所有产物一棵树：

```
D:/WBoxWork/                    ← 默认根（D 盘优先，C 盘常满）
├── projects/    迁移工程（.wbox 工程目录）
├── downloads/   可下载资源（SDK/工具/APK 样本）
├── special/     特殊资源（so/字体/未知格式待人工甄别）
├── trash/       回收区（软删除去处，可恢复）
├── cache/       缓存
└── logs/        日志
```

- 设置里可改根目录，操作时（新建工程选目录）也可临时改
- 应用数据（配置/工具/缓存）只落 `%LOCALAPPDATA%/WBox`，exe 本身只读——下载即用、卸载无痕
- 配置分两层：应用级 config.json（这台机器/这个用户）vs 工程级 spec.json（这次迁移），互不读写

### 6.3 依赖管理（wbox.deps）——新设备下载即用

| 依赖 | 用途 | 供给方式 |
|---|---|---|
| JDK 17+ | apktool 解包必需 | 自动下载 Temurin 17（约 170MB） |
| apktool jar | 「拆」步引擎 | 内置（24.5MB 打进 exe，首次解出） |
| Command Line Tools | 「补缝」步编译（hvigorw + SDK，约 2.4GB） | 自动下载；已装的本机 DevEco Studio 自动认 |

首页依赖体检自动检测，缺项带一键安装（≥1GB 先确认），装完不用重启（重新检测按钮）。SDK 挂载有源码级定位能力（hvigor-ohos-plugin 只认含 `sdk-pkg.json` 的 SDK 根，IDE 内置 SDK 自动挂载）。

### 6.4 ASCII 命名铁律（wbox.ascii_names）

DevEco Studio/hvigor 无法识别中文目录（2026-10-25 用户实测确认）。内置 1640 字拼音表（无声调，ü→v）：解包目录与工程目录用拼音首字母（`92934圆锯模拟器8` → `92934yjmnq8`），rawfile 资源目标逐段 ASCII 化，纯 ASCII 段原样保留（不误伤 `logs/1/1.png` 这类裸数字路径）。工程目录含中文时，鸿蒙工程自动落同级英文目录。配 `scripts/check_ascii_paths.py` 自动检查（15 项断言）。

### 6.5 装配模板体系（wbox/assemble.py + templates/harmony/）

17 个文件的鸿蒙工程骨架，来自两个真实工程的验证结论：Stage 模型页面登记、EntryAbility 横屏/全屏/loadContent、build-profile SDK 对齐、AppScope 三件套、oh-package ×2、lock 文件。漏一个文件编译就 00304056/00304004——已全部固化进模板与打包清单。

---

## 7. GUI 产品化功能（PySide6 桌面应用）

### 7.1 整体结构

- **首页 ⇄ 工作区** 双页：首页管工程（最近工程/新建/打开/依赖体检/设置），工作区跑五步
- **工作区三栏**：左栏清单（文件/资源/模块/行为四 tab）+ 中栏五步页面栈 + 右栏记录（编译记录/补缝/决策三 tab）+ 顶部步骤导航与保存
- **全局防遮挡设计**（2026-10-25 用户实测驱动）：表格长文字换行 + 全文 tooltip、按钮 subtitle 进 tooltip、路径 label 最小宽度 + tooltip、依赖说明换行

### 7.2 文件浏览器（左栏「文件」tab）

- 直接浏览工程目录（拆解产物 work/、rawfile、exports 任务包等），快捷按钮跳工程根/拆解产物/任务包
- **双击按类型路由打开**：
  - 文本类（smali/java/kt/ets/ts/js/json/json5/xml/txt/md/html 等 20+ 种）→ 内置只读查看器（4MB 上限、复制全部、系统默认程序外部编辑）
  - 图片/音频（png/jpg/webp/mp3/ogg/wav…）→ 系统默认程序打开
  - 其他（so/zip/ttf…）→ 试系统关联，无关联时状态栏提示
- 右键菜单：打开 / 在资源管理器中显示 / 复制路径 / 删除（移入回收区）
- **中文显示开关**：文件系统恒英文，UI 层常见目录名中文翻译（assets→资源资产、smali→字节码、logs→木头贴图…），设置里一键切回原文

### 7.3 设置中心（六个分组）

1. **使用层级**：专业开发者（五步白盒）/ 普通用户（一键流水线，建设中）
2. **工作区**：根目录浏览 + 子目录规范说明
3. **运行与部署**：任务完成后自动关机 / 避免删除文件
4. **文件命名显示**：中文显示 / 英文原文
5. **工具路径**：Java / apktool / SDK 三项（留空=自动检测），目录与文件分开选择
6. 深拷贝编辑 + 取消不改原配置 + Ok/Cancel/Apply 三态 + 原子保存

### 7.4 运行部署三要求（全部兑现）

| 要求 | 实现 |
|---|---|
| 任务完成后自动关机 | 设置开启 → 编译出 HAP 弹 60s 倒计时（立即关机=shutdown /s /t 0，取消=shutdown /a）；后台无界面时只排队不弹窗 |
| 存储优先 D 盘 | 工作区默认 D:/WBoxWork，无 D 盘退用户目录；设置可改、操作时可改 |
| 避免删除文件 | 删除一律移入工作区回收区（时间戳目录、保留可恢复）；确需删除时弹窗逐项列名明确告知；即使关闭保护也红字警告不可恢复才放行 |

### 7.5 健壮性细节

- 后台线程一次性任务放 `QThread.run()`（run 返回即线程终，杜绝 quit() 丢失导致线程永不结束的退出竞态）
- 全局异常钩子：未捕获异常弹窗展示摘要，不静默死亡、不裸 traceback 刷屏
- 离屏冒烟测试 `scripts/smoke_gui.py`：五步页面实例化 + 主窗 + 三栏联动 + 产品化断言（设置构造/软删除真移回收区/关机钩子命令/命名开关）全绿

---

## 8. 已验证战绩（真实工程，非演示数据）

| 工程 | 类型 | 结果 |
|---|---|---|
| RE.apk（明日生机） | WebView 壳应用 | 编译通过，HAP 120,491 字节；白屏根因（module.json5 错用 FA 字段 routerMap）定位并修复，真机复验确认 |
| 92934圆锯模拟器8 | libGDX 原生游戏（样本库唯一原生） | 全链路走通：拆（502 资源/14 模块/10 行为）→ 提案 → 7 决策 → 10 个 ArkTS → 装配 → **BUILD SUCCESSFUL，HAP 8,182,159 字节**；96 个 rawfile 资源、5 类素材映射（木头 6 关/锯片 8 级/木屑粒子）、切割公式与视野参数从 smali 提炼原样搬 |
| 跳石子 / 灾难模拟器 | Cordova 壳 | 甄别完成（游戏本体在本地网页，待用户拍板处理策略） |

编译链路端到端验证：Saw 工程 50 秒出 HAP；CLI 产物 unsigned 属正常（签名归 DevEco IDE）。

## 9. 技术栈与运行环境

- **语言/框架**：Python 3.13 + PySide6 6.12；契约校验 jsonschema；打包 PyInstaller 6.22（onefile + windowed，单 exe 72.9MB）
- **外部工具链**：JDK 17（Temurin）+ apktool 2.11 + DevEco Command Line Tools（hvigorw + HarmonyOS SDK）
- **数据**：v1 全部 JSON 文件存储（spec/config）；资源条目超千条再迁 SQLite
- **平台**：Windows 优先（开发与实测环境），路径层跨平台
- **测试**：契约冒烟（smoke_spec ALL PASS）/ extract 解析器 9 项 ALL PASS / GUI 离屏冒烟全绿

## 10. 双使用层级

- **专业开发者模式（当前完整可用）**：五步白盒工作台，每步可见可改可回溯，AI 副驾驶协助
- **普通用户模式（按钮已占位，一键流水线 pipeline 未完工）**：目标形态为"拖入 APK → AI 全流程 → 交付 HAP + 报告"；当前点击会明确告知建设中，不会说谎切换。**这是路线图上的下一个头等任务**

## 11. 已知边界

- 资源查看依赖本机有关联程序（so/字体等专业格式需外部工具）
- 内置文本查看器 4MB 上限（更大文件走外部程序）
- WebView 壳应用迁的是"壳"，远程网页内容不在迁移范围
- Cordova 壳样本（灾难模拟器/跳石子）的处理策略待用户拍板
- 普通用户一键流水线未建成（见第 10 章）
