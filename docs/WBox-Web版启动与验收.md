# WBox Web 版：启动、架构与验收记录

> 路线 A（原型转正）交付文档。前端原型：`D:/Game/GC/code`（React 19 + Vite 8 + Tailwind v4，秒哒平台生成后接线）；后端：`src/wbox/webapi/`（FastAPI + uvicorn，包住 wbox Python 核心）。

## 1. 架构

```
浏览器 ──► Vite dev server (127.0.0.1:5199)        开发模式
              └─ /api/* 代理 ──► wbox.webapi (127.0.0.1:8580)

浏览器 ──► wbox.webapi (127.0.0.1:8581)             生产模式（单端口）
              ├─ /api/*        FastAPI 路由（24 个端点）
              └─ /*            SPA catch-all：真实文件直出，其余回 index.html
```

- 后端**零 Qt 依赖**：PySide6 的 `ProjectSession` 不进服务端，用 duck-typing `SpecSession` 垫片（next_id/spec/save）复用 `hvigor.append_build_log`。
- 契约层铁律不变：所有 spec.json 读写经 `wbox.spec` load/save（webapi/core.py 是唯一入口），decision schema 强制 `id(dec_NNN)/topic/chosen/reason/decided_by=human/decided_at`。
- 长任务（拆/装配/编译/AI 生成）走 **POST SSE**（EventSource 只支持 GET，故 `fetch + ReadableStream` 手写解析）；协议 `data: {"t":"log"|"step"|"progress"|"done"|"error"}`，带 keep-alive 注释行。
- API Key 只存服务端（settings PUT 收、GET 不回传，只回 `api_key_set`）；AI 生成由 `/projects/{pid}/ai/generate` SSE 完成，前端不碰 key。
- pid 双轨制：ASCII 目录名（`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`）直接用；中文目录名历史工程走 base64url 绝对路径回退（`project_summary.path_b64`）。

## 2. 启动

### 开发模式（改代码用）

```bash
# 终端 1：后端
cd C:/Users/Administrator/WorkBuddy/跨平台迁移白盒工作台
PYTHONPATH=src <venv>/Scripts/python.exe -m wbox.webapi --port 8580

# 终端 2：前端（scripts/ 已在导出丢失后补齐，见 §5）
cd D:/Game/GC/code
node scripts/dev.mjs            # 等价 npm run dev，127.0.0.1:5199
```

### 生产模式（单端口，推荐演示/交付）

```bash
cd D:/Game/GC/code
node scripts/build.mjs          # 等价 npm run build，产物 dist/client/

cd C:/Users/Administrator/WorkBuddy/跨平台迁移白盒工作台
PYTHONPATH=src <venv>/Scripts/python.exe -m wbox.webapi --port 8581 \
  --dist D:/Game/GC/code/dist/client
# 打开 http://127.0.0.1:8581 即是完整产品
```

## 3. 已验证清单（2026-10-25，真实数据）

| 项 | 结果 |
|---|---|
| tsc 全量 typecheck | 0 错误 |
| vite 代理 `/api` → 8580 | health 200，8 个改动模块 dev 转换全 200 |
| `GET /api/projects` | 3 工程（RE 6 资源 / 圆锯 502 资源 4 决策 2 构建日志 / 工作台本体） |
| `GET /api/deps` | java 17.0.19 / apktool 2.11.1 / clt(deveco) 全 ok |
| `GET /api/projects/{pid}` | 圆锯完整 spec（502 资源/18 模块/10 行为） |
| RE.apk extract SSE 全链路 | apktool 实跑 → 资源 6/模块 2/行为 1 → spec 落盘 |
| 单端口 `/` `/assets/*` | 200，content-type 正确 |
| SPA 深链 `/workspace/{pid}` | 200 text/html（catch-all fallback，不依赖 Accept 头） |
| `/api/nonexistent` | 404 `{"detail":"Not Found"}` JSON 形状（不被 SPA fallback 吞） |
| 路径穿越 | `dist` 外解析被 `relative_to` 守卫拦下，回落 index.html |

**静态托管为什么不用 `StaticFiles(html=True)`**：它的 fallback 依赖请求带 `Accept: text/html`，对无浏览器头的客户端（嵌入式 webview、探针、curl）深链直接 404。改为显式 catch-all 后深链恒 200。

## 4. 页面 ↔ 端点映射

| 页面 | 端点 |
|---|---|
| 首页 HomePage | `GET /api/projects`、`GET /api/deps`、`POST /api/projects`（APK 走**服务端绝对路径**输入，Web 版无浏览器文件上传通道） |
| ① 拆 ExtractStep | `POST /api/projects/{pid}/extract`（SSE，force 重拆） |
| ② 画拼图（左栏+表） | `GET /api/projects/{pid}/proposal`、`PUT .../resources`、`PUT .../modules` |
| ③ 判断 DecideStep | `POST /api/projects/{pid}/decisions` |
| ④ 填上 FillStep | `POST .../taskpack`（zip 下载）、`POST .../draft`（粘贴导入）、`POST .../ai/generate`（SSE，key 服务端持有） |
| ⑤ 补缝 SealStep | `PUT .../seams`、`POST .../assemble`（SSE）→ `POST .../build`（SSE）→ `GET .../harmony-dir` |
| 文件预览 FilePreview | `GET .../files`、`GET .../file`、`GET .../download` |

## 5. scripts/ 丢失事故与修复

秒哒平台导出时丢了整个 `scripts/` 目录，`package.json` 四个 script 全断（dev/build/prepare）。已补最小跨平台实现：

- `scripts/dev.mjs` —— `vite.createServer` + `fileURLToPath` 解析配置（Windows 下 `new URL(...).pathname` 带前导斜杠会拼出 `D:\D:\...`，必须用 `fileURLToPath`）
- `scripts/build.mjs` —— `vite.build`
- `scripts/setup-git-hooks.mjs` —— no-op 占位（防 `npm install` 的 prepare 钩子再失败）
- `package.json` 的 `build` 从 `bash scripts/build.sh` 改为 `node scripts/build.mjs`（去掉对 Git Bash 的依赖）

## 6. 已知边界

- lite 模式流水线在桌面版是占位，Web 版同样只跑 pro 链路。
- 依赖安装（java/apktool/clt）仍只在桌面版提供，Web 版只做体检展示。
- 删除工程走 `DELETE /api/projects/{pid}`（从 recent 摘除），不删盘上文件——与桌面版软删除语义一致。
- 单 worker uvicorn：长任务在 daemon 线程，`_LOCKS` 做 per-project 并发守卫（409）。
