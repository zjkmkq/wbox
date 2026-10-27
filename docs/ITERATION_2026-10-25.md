# WBox 项目迭代与总结（2026-10-25）

> 结论先行：**技术逻辑没有被推翻，被推翻的是产品形态。**
> 聊天两小时能出初步迁移，应用五步出不来——差别不在算法，在"中间态由谁承担"。
> 本轮迭代已落地并验证：装配自动化（assemble.py）+ 中文目录铁律（ASCII 化）。

---

## 一、诊断：为什么"和 AI 聊两小时"能成，五步工作台出不来

### 1.1 直接答案

不是这个应用有根本性的技术问题，是**产品定位错了**。

同一套技术逻辑（参照重做、reference-closure BFS 识别自有代码、FILE 格式契约、
hvigor 编译验证），在 AI 聊天里两小时能交出可编译的鸿蒙草案，在工作台里却
"一直有问题、一次完整结果都没出来"。差异只有一处：

| 维度 | AI 聊天模式 | 五步工作台 |
|---|---|---|
| 中间态由谁承担 | **AI 全包**（拆解、映射、生成、修错） | **用户全包**（拖文件、粘贴、选目录、读警告） |
| 人的角色 | 验收者 + 赞助者（复制粘贴、拍板） | 操作员（每步都要懂"为什么"） |
| 失败时的表现 | AI 自己绕过去 | 弹一个错，人等下一句指令 |
| 上手门槛 | 会打字 | 要理解五步契约、FILE 格式、工程目录概念 |

人机分工倒挂了：迁移这件事 90% 工作量在"执行"，不在"判断"。聊天模式让 AI
当执行主力、人当验收者，所以快；工作台把执行拆成五步交给用户当操作员，
所以慢、所以觉得"有门槛"。

### 1.2 五步拆解本身是对的

拆 → 画拼图 → 判断 → 填上 → 补缝，真实反映了迁移工程的阶段。问题在于
**把"过程白盒"做成了主路径**：契约层、seam、决策记录是工程质量资产，
对"我想要一个 HAP"的一次性用户是负担不是价值。

### 1.3 已暴露的交互契约坑（都是产品级，不是 bug 级）

- C 步"写入零个文件"：用户把任务包/draft 拖进去，应用只当纯文本收——
  用户心智是"拖进去就能用"，数据流是"只吃 AI 产出文本"。
- seal 步默认目录是 apktool 解包目录：用户照默认值点编译必炸。
- 中文目录：DevEco Studio 不识别，产物路径带中文直接编译失败（本轮修复）。

---

## 二、本轮迭代交付（2026-10-24 ~ 10-25，全部真实验证）

### 2.1 assemble.py —— 消灭最大手工断点（新模块，已验证）

过去每次迁移的最后一步是**人工**搭鸿蒙工程：拷骨架、拼 module.json5、
搬 rawfile、写 main_pages.json、改 EntryAbility——CircularSaw 工程当初就是
这样手工拼出来的。现在一条命令：

```
python -m wbox.assemble <spec.json> [-o 输出目录]
```

- 骨架模板内置（`src/wbox/templates/harmony/`，17 个文件，取自两个真实
  可编译工程）：AppScope / build-profile / hvigor-config / module.json5
  （Stage 模型 `pages` 字段，白屏铁律）/ EntryAbility / hvigorfile
- draft 产物按原相对路径并入；页面登记从 @Entry 结构体反推（以产物为准，
  不靠提案猜）；资源按提案 resource_moves 搬进 rawfile（原名→ASCII 名）
- **验收**：重装圆锯工程 → `BUILD SUCCESSFUL`，HAP 8,013,288 字节
  （15 代码文件 + 102 资源 0 缺失 + 1 页面登记正确）

### 2.2 中文目录铁律（用户实测确认后全链路修复）

DevEco Studio / hvigor 无法识别中文目录。新增 `wbox/ascii_names.py`：
内置 1640 字拼音表（无声调），中文→拼音全拼，表外字丢弃，空名兜底
`app+哈希`。改造 5 个消费方：

| 位置 | 改动 |
|---|---|
| extract.py | 解包目录 `work/92934圆锯模拟器8` → `work/92934yuanjumoniqi8` |
| extract_step.py | GUI 同步英文目录 + 界面提示 |
| assemble.py | 默认输出：工程路径含中文时落**同级英文目录**（seal 步探测已覆盖） |
| mainwin.py | 新建工程目录名 ASCII 化 + 中文存放目录警告 |
| plan.py | rawfile 资源目标逐段 ASCII 化（"圆锯.png"→"yuanju.png"） |

存量工程 `work/92934圆锯模拟器8` 已改名为 `92934yuanjumoniqi8`；
旧中文目录仍可被定位（兼容逻辑 + 检查脚本断言）。

### 2.3 自动检查（`scripts/check_ascii_paths.py`，22 项断言）

样本转换 / 模板树 ASCII / 模板必备文件清单 / 工程三层目录扫描 /
解包目录定位 / 真跑 assemble 验落点与页面登记 / 存量中文目录兼容。
**当前 22/0 全绿**（`python scripts/check_ascii_paths.py`，退出码 0）。

### 2.4 本轮踩坑记录（都已转成断言）

1. **find 输出被 head 截断**：漏掉 `entry/build-profile.json5` 和
   `entry/hvigorfile.ts` → 装配工程 00304056。已列模板必备清单进检查。
2. **out_dir 被默认逻辑吞掉**：显式输出目录被忽略，产物静默写进
   `D:/Game/GC/harmony/`，检查还全绿。已加"尊重显式 out_dir"断言。
3. **@Entry 正则写严**：`@Component` 无括号导致页面登记 0 个（白屏隐患）。

### 2.5 回归状态

- GUI 冒烟：SMOKE OK（五步页面、三栏联动、后台线程回收）
- 单元测试：test_extract 9 项 ALL PASS / smoke_spec 4 项 ALL PASS
- PyInstaller 规格已补模板目录打包（漏一个模板文件 = 打包版必炸）

---

## 三、项目现状总结

### 3.1 已验证资产（硬成果，不怕推翻重来）

- **契约层**：spec.json + schema 严格校验，原子写，版本化迁移链
- **自有代码识别**：reference-closure BFS（只从自有 manifest 入口发散），
  混淆圆锯工程实测 132 自有类 / 8932 库类，w0 游戏核心不漏
- **FILE 格式契约**：任务包 → 任意 AI → 粘贴/API 回 import，round-trip
  字节级一致
- **装配 + 编译链路**：assemble.py + hvigor.run_build，HAP 8,013,288 字节
- **白屏根因**：module.json5 错用 FA 字段 routerMap（应为 pages），
  Saw/RE/CircularSaw 三工程同症，已修并真机复验
- **ArkTS 编译知识**：CanvasRenderingContext2D 全局类、ctx.width、
  setInterval 代替 rAF、setWindowLayoutFullScreen 归 EntryAbility
- **中文目录铁律**：ascii_names + 22 项自动检查

### 3.2 未完成（按优先级）

1. **剩余 117 个逻辑类未迁移**（132 - 15）。下一批：w0/c 游戏世界、
   w0/g InputProcessor、scene2d UI 层（y0/b1/c1/g4/d1）。
   广告 SDK t1/f4 约 23 类按方法论 §3 单机化不迁（seam_005 wontfix）。
2. **一键迁移管线（pipeline.py）**：本轮诊断的直接产物——把五步收进
   一条流水线（APK → 拆 → 提案 → 默认决策 → AI 生成 → 装配 → 编译 →
   HAP + 报告），GUI 首页加大按钮。五步工作台降级"专家模式"保留。
   这是消灭"门槛"的关键一步，尚未开工。
3. **行为验收**：seam_105 切割手感、seam_001 主循环、seam_003 输入回调
   全 return false——需真机对比原版后才允许标 verified。
4. **PyInstaller 出包**（#16）：模板已进 datas，待重新打包验证。

### 3.3 结论

应用不是"根本上有问题"，是**把工程师的过程工具当成了产品**。
技术资产全部有效且被真实工程验证；迭代方向明确：主线改一键流水线，
白盒五步降级为专家模式。本轮交付的 assemble.py 已经消掉了最大的
手工断点，是这条路上第一个可复用的自动环节。

---

*附：本轮文件变更——新增 `src/wbox/ascii_names.py`、`src/wbox/assemble.py`、
`scripts/check_ascii_paths.py`、`src/wbox/templates/harmony/`（17 文件）；
修改 `extract.py`、`plan.py`、`hvigor.py`（补 CLI）、`mainwin.py`、
`extract_step.py`、`wbox.spec`。*
