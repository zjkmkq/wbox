# 跨平台迁移白盒工作台 · WBox

> Android → HarmonyOS NEXT **白盒迁移**本地桌面工作台：自动拆解原应用 → 生成结构提案 → 人工裁决 → AI 辅助重写 ArkTS → 自动装配成可编译工程 → 命令行编译验证，全过程留痕可回溯。

本仓库是 **WBox 工具本身的源码与文档**。它不是某个具体游戏的迁移成品，而是一套「把 APK 参照重做成鸿蒙工程」的工作流与契约层。

---

## 目录

- [项目简介](#项目简介)
- [核心设计哲学（四条铁律）](#核心设计哲学四条铁律)
- [能做什么 / 不能做什么](#能做什么--不能做什么)
- [五步流水线](#五步流水线)
- [已验证案例](#已验证案例)
- [安装与运行（从源码）](#安装与运行从源码)
- [打包成单文件 exe](#打包成单文件-exe)
- [如何正确使用（必读）](#如何正确使用必读)
- [当前局限性](#当前局限性)
- [未来可升级方向](#未来可升级方向)
- [目录结构](#目录结构)
- [许可证](#许可证)

---

## 项目简介

把 Android 应用迁到鸿蒙，行业现状是三条死路：

| 路线 | 问题 |
|---|---|
| 逐行翻译 Java/Kotlin → ArkTS | 鸿蒙没有 Android 运行时，翻译出来的代码跑不起来，白费人力 |
| 在线「一键转换」服务 | 黑盒、不可控，应用要上传到别人服务器，商业资产泄露 |
| 从零重写 | 没有原应用细节参照，玩法/数值/资源全靠猜，做出来不像 |

WBox 走第四条路：**参照重做（reference-rebuild）**。原应用被拆成「资源 / 逻辑 / 行为」三类参考，鸿蒙侧对着参考重新做，差异（缝 / seam）被显式记录、逐条验证。AI 是副驾驶负责搬重物，人保留判断权——契约层 `decided_by` 恒为 `human`，不替人拍板。

> 一句话：WBox 把「和 AI 聊两小时能出的可编译鸿蒙草案」固化成一套可留痕、可回溯、可复用的工程工具。

---

## 核心设计哲学（四条铁律）

这些不是口号，是写死在代码里的规则：

1. **契约唯一纽带**：整个工作台只有一个数据文件 `spec.json`（迁移契约），所有模块只准通过 `wbox.spec` 契约层读写，禁止各自 `json.load`。契约经 `spec.schema.json` 严格校验（`additionalProperties=false`，多一个字段都不收）。
2. **版本化迁移链**：`spec_version` 与代码 `SPEC_VERSION` 不符时走注册的迁移链逐版升级，禁止手改文件；保存为原子写（临时文件 + `os.replace`），崩溃不留半个文件。
3. **参照重做，不逐行翻译**：AI 指令模板固化了真实项目的验证结论——数值原样搬、API 26 差异、ArkTS 禁则、缝记录规范。
4. **工程落地优先**：所有数值精确（如射程 120 = 6 格），拒绝引擎实现不了的功能，产物必须过真编译，不以「看起来对」交差。

---

## 能做什么 / 不能做什么

**能做：**
- 解包 APK，产出机器可推导的资源 / 模块 / 行为三段清单（不猜逻辑细节）。
- 把清单映射成鸿蒙结构初稿（资源→rawfile 搬迁表、模块→逻辑类/页面/组件、行为→页面/对话框），提案可逐条改、可编辑即存。
- 人工裁决开放问题，决策写入 `spec.decisions`（`decided_by` 恒为 `human`）。
- 按提案生成 ArkTS 草案，落 `draft/`，支持三种通道：任务包导出 / OpenAI 兼容 API 直连 / 粘贴导入。
- 自动装配成可编译鸿蒙工程（`assemble.py` + 内置 17 文件骨架模板），跑 hvigor 编译，管理缝状态板。

**不能做 / 不属于范围：**
- 不是逐行翻译器，也不是在线黑盒转换器。
- WebView 壳应用迁的是「壳 + 桥接」，远程网页内容不在迁移范围。
- 目前**只有专业开发者模式（五步白盒）**完整可用；普通用户一键流水线尚未建成（见[局限性](#当前局限性)）。

---

## 五步流水线

```
APK ──①拆──▶ spec 三段清单 ──②画拼图──▶ 结构提案 ──③判断──▶ 人工决策
                                                              │
HAP ◀──⑤补缝── 可编译鸿蒙工程 ◀──装配器── draft/ ArkTS ◀──④填上──┘
                    │                                        ▲
                    └── hvigor 流式编译 ◀── 编译记录/缝状态板  三通道（任务包/API/粘贴）
```

每一步在 GUI 里是一个页面，在 CLI 里是一个模块（`python -m wbox.extract` 等），两层共用同一契约层。

| 步 | 模块 | 做什么 |
|---|---|---|
| ① 拆 | `wbox.extract` | apktool 流式解包 → 资源/模块/行为清单写进 spec（自有代码用 manifest 入口 + smali BFS 闭包识别，混淆工程也能分离库代码） |
| ② 画拼图 | `wbox.plan` | 确定性启发式映射成鸿蒙结构初稿，三张可编辑表（资源搬迁/逻辑类/UI 单元） |
| ③ 判断 | `decide_step` | 开放问题逐条人工裁决，写进 `spec.decisions` |
| ④ 填上 | `wbox.taskpack`/`aiclient`/`draft` | 按提案生成 ArkTS 草案，三通道统一走 `wbox.draft` 落盘 |
| ⑤ 补缝 | `wbox.hvigor`/`assemble` | 装配成可编译工程 → hvigor 流式编译 → 缝状态板管理 |

GUI 另有三个独立页面：**形态诊断仪**（丢一个 APK 先回答「是什么形态/能不能迁/几步/有哪些坑」）、**迁移知识库**（按形态浏览模板与教程）、**排障台**（汇总所有工程的缝/失败案例/日志检索）。

---

## 已验证案例

真实工程，非演示数据：

| 工程 | 类型 | 结果 |
|---|---|---|
| RE.apk（明日生机） | WebView 壳应用 | 编译通过，HAP 120,491 字节；白屏根因（`module.json5` 错用 FA 字段 `routerMap`）定位并修复，真机复验确认 |
| 92934圆锯模拟器8 | libGDX 原生游戏（样本库唯一原生） | 全链路走通：拆（502 资源 / 14 模块 / 10 行为）→ 提案 → 7 决策 → 10 个 ArkTS → 装配 → **BUILD SUCCESSFUL，HAP 8,182,159 字节**；切割公式与视野参数从 smali 提炼原样搬 |
| 跳石子 / 灾难模拟器（Wreckbox） | Cordova 壳 + 本地 H5 | 灾难模拟器（Wreckbox）**正面案例**：拆包 3,379 资源 / 9 模块，draft 由 AI（豆包）粘贴生成，中途仅 1 次 AI 引入的编译错误、修补后即过，真机一遍就过，BUILD SUCCESSFUL HAP 480,178 字节 |

> 形态模板与迁移教程见 `src/wbox/shapes/`（5 个形态）与 `src/wbox/tutorials/`（11 篇）。

---

## 安装与运行（从源码）

**环境要求**
- Python 3.13（≥3.10 亦可），自带 venv 即可
- JDK 17+（apktool 解包必需；首次会自动下载 Temurin 17）
- apktool：**本仓库不附带其二进制**（第三方 Apache-2.0 工具，来源与许可证请自行确认）。请先运行 `python scripts/fetch_apktool.py` 自动从官方发布页下载 `apktool.jar`（约 24.5 MB）到 `tools/apktool/`；也可手动从 https://github.com/iBotPeaches/Apktool/releases 下载后放入该目录。
- DevEco Command Line Tools + HarmonyOS SDK（仅 ⑤ 步编译鸿蒙工程需要；已装 DevEco Studio 会自动认）

**步骤**

```bash
# 1. 建虚拟环境并安装依赖
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt

# 2. 启动图形界面
python -m wbox.gui
```

也可走纯 CLI 单步：`python -m wbox.extract <apk>`、`python -m wbox.assemble <spec.json> [-o 输出目录]` 等。

> 首次打开会检测依赖并在首页提示缺失项；JDK/SDK 可按提示一键下载，装完不需重启。

---

## 打包成单文件 exe

```bash
pip install PyInstaller==6.22.3
pyinstaller --noconfirm --clean wbox.spec
# 产物：dist/WBox.exe（满血版约 237 MB，内嵌 QtWebEngine 联网检索）
```

- **瘦身版**（约 74 MB，不含内嵌浏览器，帮助中心降级为「用系统浏览器打开」）：`set WBOX_SLIM=1` 后再打包。
- **打包注意事项（排坑）**：
  - 在某些被安全删除 shim 拦截的环境里，PyInstaller 末尾替换 `dist/WBox.exe` 会被拦。遇到 `safe-delete 操作失败` / `PermissionError WinError 5`，先停掉残留进程 `Stop-Process -Name WBox -Force`，并以 `CODEBUDDY_SAFE_DELETE_ENABLED=0` 运行打包命令。
  - `wbox.spec` 已把 `shapes/`、`tutorials/`、`templates/harmony/`、`spec.schema.json`、`apktool.jar` 全部打进 datas；漏一个模板文件 = 打包版必炸，已固化进规格与检查。**打包前请先执行 `python scripts/fetch_apktool.py` 取得 apktool.jar**，否则 datas 缺失会直接失败。

冷启动自检：`scripts/verify_exe.py --selftest`（确认打包产物里形态模板与教程库都在、五个入口都能打开）。

---

## 如何正确使用（必读）

这套工具「正确用法」和「直觉用法」不一样，下面是最容易踩的坑：

1. **路径必须全英文（ASCII 铁律）**。DevEco Studio / hvigor 无法识别中文目录——工程名、解包目录、存放目录、鸿蒙工程输出目录含中文都会编译失败。WBox 会自动把工程名/资源名拼音化（内置 1640 字拼音表，`92934圆锯模拟器8` → `92934yjmnq8`），但**你选的「存放目录」本身也要是英文路径**（如 `D:\wbox\`）。
2. **④ 步「填上」吃的是 AI 产出文本，不是「拖入即用」**。把任务包 / draft 粘进应用，它只当纯文本收；它的心智是「AI 生成的 ArkTS 落盘」，不是「我丢个 APK 它就出 HAP」。真正的 HAP 在 ⑤ 步由 hvigor 编译产出。
3. **白屏 ≠ 编译失败**。Stage 模型（API 12+）的 `module.json5` 必须写 `"pages": "$profile:main_pages"`；`routerMap` 是 FA 模型老字段，错用它会导致页面不挂载、系统白底但进程不死。模板已固化正确写法，但自己手写页面登记时务必注意。
4. **行为缝（seam）必须真机对比后才允许标「已验证」**。界面会常驻提示：仅凭代码推断就标 verified 是不允许的。逻辑缝 / 资源缝可凭编译与静态分析判定。
5. **⑤ 步默认输出目录别乱改**。装配器尊重你显式指定的 `[-o]`，但别把输出指到 apktool 解包目录（照默认点编译必炸）。
6. **当前只有「专业开发者模式」能用**。「普通用户 / 一键流水线」按钮已占位但点击会明确告知「建设中」，不会假装能用——别被它误导。
7. **契约层是事实源**。`spec.json` 经严格 schema 校验，多一个字段都拒收；改它请走代码层的 `wbox.spec`，不要手改 JSON 文件（版本不符会自动走迁移链）。
8. **资源查看依赖本机关联程序**。内置文本查看器有 4 MB 上限，更大的 smali/字节码文件会走系统默认程序打开；so / 字体等专业格式需你本机有对应工具。

---

## 当前局限性

坦诚列出，方便你判断是否要继续：

1. **一键流水线 / 普通用户模式未建成**。当前完整可用的只有专业五步白盒模式。这是产品形态的下一个头等任务——五步把「过程白盒」做成了主路径，对「我只想要一个 HAP」的一次性用户是负担。
2. **WebView 壳应用只迁「壳」**。远程网页内容不在迁移范围内，壳迁过去后网页本身需另行处理或保留远程访问。
3. **Cordova 壳样本（灾难模拟器 / 跳石子）处理策略未拍板**。已甄别完成（游戏本体在本地 `assets/public` 网页），但「整包搬 / 精简 / 重写」尚未决策。
4. **圆锯工程（libGDX 原生）仍有大量逻辑未迁移**。实测 132 个自有类里只迁了 15 个；剩余 117 个（游戏世界、输入处理、scene2d UI 层等）待补。
5. **行为验收未完成**。seam_105（切割手感）、seam_001（主循环）、seam_003（输入回调）均 `return false`，需真机对比原版后才能标 verified。
6. **测试覆盖有限**。现有契约冒烟 + extract 单测 + GUI 离屏冒烟，缺少端到端 CI 与更系统的回归；目前靠 `scripts/smoke_gui.py`、`scripts/check_text_clip.py`、`scripts/check_ascii_paths.py` 三件套兜底。
7. **仅 Windows 实测**。DevEco Studio / hvigor 原生 Windows / macOS；路径层做了跨平台抽象但未在 Linux / macOS 真跑。
8. **打包产物偏大**。满血版 237 MB（含 QtWebEngine 内嵌 Bing 联网检索）；瘦身版 74 MB 但帮助中心降级。
9. **x86_64 模拟器没有 WebGL**。H5 游戏会回落 Canvas，颜色 tint 需注入层「tint bake」补偿（已处理），但模拟器截图不能当作最终验收——必须在真机复核。
10. **资源条目超千条仍全 JSON 存储**。未迁 SQLite；超大工程（如几千条资源）解析可能偏慢，但当前样本均未触发瓶颈。

---

## 未来可升级方向

按优先级与可行性排序，供以后有空时参考：

1. **一键迁移流水线 `pipeline.py`（最高优先）**：APK → 拆 → 提案 → 默认决策 → AI 生成 → 装配 → 编译 → 输出 HAP + 报告。把五步收进一条流水线，GUI 首页加大按钮；五步白盒降级为「专家模式」。这是消灭用户门槛的关键一步。
2. **补全圆锯游戏逻辑 + 行为真机验收**：迁移剩余 117 个自有类（w0/c 世界、scene2d UI 层等），并把 seam_105/001/003 拿真机对比原版后标 verified。
3. **多 AI 厂商 / 本地模型通道**：除 OpenAI 兼容端点外，接入 Ollama 等本地模型直连，降低对网页 AI 的依赖，也利于离线 / 隐私场景。
4. **形态模板自动侦测 + 扩充形态库**：已覆盖 Cordova / WebView 远程包 / libGDX 原生 / Unity IL2CPP / 原生 Android；可扩展 React Native、微信小程序壳、Flutter 等少数派引擎。
5. **资源条目超千条迁 SQLite**：解决超大工程的 JSON 解析性能天花板。
6. **跨平台 exe + CI 自动构建**：用 GitHub Actions 自动出 Windows / macOS / AppImage 包，省去手工打包（也绕开本地安全删除 shim 的坑）。
7. **云构建 / 在线协作**：把「拆解 + 编译」这类重活放云端，本地只管判断——这正好呼应「聊天模式比工作台快」的本质（中间态由谁承担）。
8. **测试与质量门禁**：单元测试扩大覆盖、加入端到端用例、接 CI 卡点，避免回归。
9. **普通用户模式 UI 完善**：进度可视化、错误自愈提示、文案引导，让非开发者也能出 HAP。
10. **文档 / 教程持续沉淀**：已 11 篇教程 + 5 形态模板，可继续补充更多「少数派引擎」的迁移经验与踩坑记录。

---

## 目录结构

```
wbox/                        仓库根
├── src/wbox/                工具源码（契约层 / Extract / Plan / Draft / Assemble / hvigor / GUI）
│   ├── shapes/              形态模板库（5 个，诊断仪与知识库的数据源）
│   ├── tutorials/           迁移教程库（11 篇，帮助中心数据源）
│   ├── templates/harmony/   鸿蒙工程骨架模板（17 文件，装配器使用）
│   └── gui/                 PySide6 桌面应用（首页 + 工作区 + 诊断仪/知识库/排障台/工具箱）
├── scripts/                 开发 / 验证脚本（冒烟、文本遮挡检查、ASCII 路径检查、浏览器探针、exe 自检）
├── docs/                    项目文档（全功能描述、迭代总结、Web 版验收等）
├── tools/apktool/           apktool.jar 放置处（**不入库**，运行 scripts/fetch_apktool.py 获取）
├── spec.schema.json         迁移契约 schema（严格校验）
├── spec.example.json        契约示例
├── wbox.spec                PyInstaller 打包规格
├── pyproject.toml           包元数据与依赖
├── requirements.txt         运行 / 打包依赖
└── README.md                本文件
```

> 不入库的内容（见 `.gitignore`）：构建产物 `build/ dist/`、运行时生成的 `work/`（解包）、`node_modules/`、`draft/`、`exports/`、`Downloads/`（APK 样本，来自网络、版权归原作者，**不随仓库分发**）、本机配置 `wbox.config.json`、具体工程数据 `spec.json`、本地记忆 `.workbuddy/`、以及第三方工具 `tools/apktool/apktool.jar`（来源网络，请用 `scripts/fetch_apktool.py` 自行获取）。

---

## 许可证

[MIT](./LICENSE)。详见仓库内 `LICENSE` 文件。

---

*本 README 整合自项目内的《全功能详细描述》《迭代与总结》《交付报告》以及契约层 / 装配器 / ASCII 命名等已实现模块，描述的是与源码一一对应的真实能力，不含未建成功能的虚标。*
