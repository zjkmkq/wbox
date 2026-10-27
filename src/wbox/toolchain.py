"""wbox.toolchain —— 内置工具链：编译 / 装机 / 启动 / 截图 / 巡检 / 探针。

存在理由：`scripts/` 里已经验证过一整套能力（verify_device.py 的"装包→启动→等
首帧→截图→拉回"、hvigor 的流式编译、browser_probe.js 的渲染探针），但它们只能
在命令行里用，界面上点不到。本模块把这些能力收敛成**不依赖 GUI 的函数**，
由 gui/pages/tools.py 按钮化。

硬规则（写死，别绕）：
1. hdc 必须用 `subprocess` 直接调**exe 绝对路径**，不经 Git Bash/中间 shell——
   经 shell 后参数会被再解析一遍，中文路径与空格直接炸。
2. hdc 经常"返回非零但实际成功"（bm install 尤其常见），所以判定以**输出关键字**
   为准，不唯退出码；但输出必须原样回传，不许吞。
3. 所有长任务都提供 `on_line(str)` 回调，GUI 侧挂到 QThread 上做流式日志。
4. 本模块不 import GUI、不碰 spec，纯函数式，便于 CLI 与测试直接调。

CLI：
    python -m wbox.toolchain devices
    python -m wbox.toolchain build  <鸿蒙工程目录>
    python -m wbox.toolchain inspect --hap x.hap --bundle com.foo --wait 15
"""

from __future__ import annotations

import functools
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from wbox import config as app_config
from wbox import deps as dep_mod
from wbox.paths import clt_dir

LineCallback = Callable[[str], None] | None

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
REMOTE_TMP = "/data/local/tmp"
REMOTE_HAP = f"{REMOTE_TMP}/wbox-tool.hap"
REMOTE_SHOT = f"{REMOTE_TMP}/wbox-shot.jpeg"

# bm install / aa start 的成功特征串（hdc 退出码不可靠，以输出为准）
_OK_INSTALL = ("install bundle successfully", "success", "Success")
_ERR_HINTS = ("error", "failed", "Failure", "ERRNO", "not found")

# 中断：GUI「中断」按钮 → cancel_active()；各任务在步骤之间查 cancelled()。
# 单个子进程由 kill 搞定（已在跑的长任务立即可停），多步任务靠标志位在下一步止步。
_ACTIVE_PROCS: list[subprocess.Popen] = []
_CANCEL = threading.Event()


# ---------------------------------------------------------------- 中断控制


def cancelled() -> bool:
    """当前是否被要求中断（任务在步骤之间查）。"""
    return _CANCEL.is_set()


def cancel_active() -> int:
    """终止正在跑的子进程并置中断标志，返回被终止的进程数。"""
    _CANCEL.set()
    killed = 0
    for proc in list(_ACTIVE_PROCS):
        try:
            if proc.poll() is None:
                proc.kill()
                killed += 1
        except Exception:  # noqa: BLE001  进程可能已退出
            continue
    return killed


def reset_cancel() -> None:
    """新任务开始前清除中断标志（否则上一次的中断会传染下一个任务）。"""
    _CANCEL.clear()


# ---------------------------------------------------------------- 数据结构


@dataclass
class ToolResult:
    ok: bool
    message: str = ""
    detail: str = ""
    artifact: str = ""      # 产物路径（HAP / 截图）

    def as_text(self) -> str:
        parts = [self.message or ("成功" if self.ok else "失败")]
        if self.artifact:
            parts.append(f"产物：{self.artifact}")
        if self.detail:
            parts.append(self.detail)
        return "　".join(parts)


@dataclass
class DeviceInfo:
    serial: str = ""
    extra: str = ""

    def as_text(self) -> str:
        return f"{self.serial}{('　' + self.extra) if self.extra else ''}"


# ---------------------------------------------------------------- 基础执行


def _emit(on_line: LineCallback, text: str) -> None:
    if on_line is not None:
        on_line(str(text))


def run_cmd(cmd: list[str], on_line: LineCallback = None, timeout: int = 180,
            cwd: str | None = None, env: dict | None = None) -> tuple[int, str]:
    """跑一条外部命令，逐行回调输出，返回 (退出码, 合并输出)。不抛异常。

    进程会登记进 `_ACTIVE_PROCS`，GUI 的「中断」按钮调 `cancel_active()` 直接 kill，
    这是当前唯一可靠的打断手段（任务内部只在**步骤之间**检查中断标志）。
    """
    if cancelled():
        _emit(on_line, "[已中断] 任务已被用户中止")
        return 130, "[已中断]"
    _emit(on_line, "$ " + " ".join(cmd))
    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors="replace", bufsize=1, creationflags=_CREATE_NO_WINDOW,
        )
    except OSError as e:
        _emit(on_line, f"[启动失败] {e}")
        return 127, str(e)
    _ACTIVE_PROCS.append(proc)
    chunks: list[str] = []
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            text = line.rstrip()
            chunks.append(text)
            _emit(on_line, text)
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        _emit(on_line, f"[超时] {timeout}s，已终止")
        return 124, "\n".join(chunks)
    finally:
        if proc in _ACTIVE_PROCS:
            _ACTIVE_PROCS.remove(proc)
    return code, "\n".join(chunks)


# ---------------------------------------------------------------- hdc 定位


def _hdc_candidates(cfg: dict | None = None) -> list[Path]:
    """按"配置 → 已解析 SDK → 命令行工具 → DevEco 安装 → PATH"的顺序找 hdc。"""
    cands: list[Path] = []
    cfg = cfg or app_config.load()
    configured = str((cfg.get("tools") or {}).get("hdc_path") or "").strip()
    if configured:
        cands.append(Path(configured))
    tc = dep_mod.resolve_toolchain(cfg)
    if tc is not None:
        cands.append(Path(tc.sdk_home) / "default" / "openharmony" / "toolchains" / "hdc.exe")
    cands.append(clt_dir() / "sdk" / "default" / "openharmony" / "toolchains" / "hdc.exe")
    for root in dep_mod._DEVECO_CANDIDATES:   # noqa: SLF001  同项目内复用候选表
        cands.append(root / "sdk" / "default" / "openharmony" / "toolchains" / "hdc.exe")
    exe = shutil.which("hdc")
    if exe:
        cands.append(Path(exe))
    return cands


def find_hdc(cfg: dict | None = None) -> str:
    """返回可用的 hdc 绝对路径；找不到返回空串（GUI 据此禁用按钮并说明原因）。"""
    for cand in _hdc_candidates(cfg):
        try:
            if cand.is_file():
                return str(cand)
        except OSError:
            continue
    return ""


def hdc(*args: str, cfg: dict | None = None, on_line: LineCallback = None,
        timeout: int = 180) -> tuple[int, str]:
    """跑一条 hdc 命令（全路径直调 exe，不经 shell）。"""
    exe = find_hdc(cfg)
    if not exe:
        return 127, "未找到 hdc.exe：请安装 HarmonyOS 命令行工具（设置 → 插件与依赖）"
    return run_cmd([exe, *args], on_line=on_line, timeout=timeout)


# ---------------------------------------------------------------- 设备


def list_targets(cfg: dict | None = None, on_line: LineCallback = None) -> tuple[list[DeviceInfo], str]:
    """hdc list targets —— 返回 (设备列表, 原始输出)。无设备时列表为空。"""
    code, out = hdc("list", "targets", cfg=cfg, on_line=on_line, timeout=30)
    devices: list[DeviceInfo] = []
    for raw in (out or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("$ ") or line.lower() == "[empty]":
            continue
        if "empty" in line.lower():
            continue
        if code == 127:
            continue
        devices.append(DeviceInfo(serial=line))
    return devices, out


# ---------------------------------------------------------------- 编译


def build_project(project_dir: str | Path, on_line: LineCallback = None,
                  cfg: dict | None = None, timeout: int = 900) -> ToolResult:
    """编译鸿蒙工程（assembleHap），返回 HAP 路径。逻辑全在 wbox.hvigor。"""
    from wbox import hvigor as hvigor_mod

    project = Path(project_dir)
    if not project.is_dir():
        return ToolResult(False, f"工程目录不存在：{project}")
    res = hvigor_mod.run_build(project, on_line=on_line, cfg=cfg, timeout=timeout)
    if res.ok:
        return ToolResult(True, "编译成功：" + res.summary, artifact=res.hap_path)
    return ToolResult(False, "编译失败：" + (res.error or "未知错误"), detail=res.log_tail[-2000:])


# ---------------------------------------------------------------- 装机 / 启动 / 截图


def install_hap(hap: str | Path, bundle: str = "", on_line: LineCallback = None,
                cfg: dict | None = None) -> ToolResult:
    """推送 HAP 到设备并 bm install。bundle 仅用于日志提示。"""
    path = Path(hap)
    if not path.is_file():
        return ToolResult(False, f"HAP 不存在：{path}")
    _emit(on_line, f"推送 {path.name}（{path.stat().st_size:,} 字节）→ {REMOTE_HAP}")
    code, out = hdc("file", "send", str(path), REMOTE_HAP, cfg=cfg, on_line=on_line, timeout=300)
    if code != 0 and "success" not in out.lower():
        if cancelled():
            return ToolResult(False, "已中断", detail=out[-1500:])
        return ToolResult(False, "推送失败", detail=out[-1500:])
    code, out = hdc("shell", f"bm install -p {REMOTE_HAP}", cfg=cfg, on_line=on_line, timeout=300)
    low = out.lower()
    if any(h in out for h in _OK_INSTALL) or "successful" in low:
        name = f"（bundleName={bundle}）" if bundle else ""
        return ToolResult(True, f"安装成功{name}", artifact=str(path))
    if any(h.lower() in low for h in _ERR_HINTS):
        return ToolResult(False, "安装失败", detail=out[-1500:])
    return ToolResult(False, f"安装结果不确定（退出码 {code}）", detail=out[-1500:])


def start_app(bundle: str, ability: str = "EntryAbility", on_line: LineCallback = None,
              cfg: dict | None = None) -> ToolResult:
    """重启应用：aa force-stop → aa start。"""
    if not bundle.strip():
        return ToolResult(False, "未填 bundleName，无法启动")
    hdc("shell", f"aa force-stop {bundle}", cfg=cfg, on_line=on_line, timeout=60)
    if cancelled():
        return ToolResult(False, "已中断")
    time.sleep(1)
    code, out = hdc("shell", f"aa start -a {ability} -b {bundle}", cfg=cfg,
                    on_line=on_line, timeout=60)
    if cancelled():
        return ToolResult(False, "已中断", detail=out[-1500:])
    if "start ability successfully" in out.lower() or "success" in out.lower() or code == 0:
        return ToolResult(True, f"已启动 {bundle}/{ability}")
    return ToolResult(False, "启动失败", detail=out[-1500:])


def snapshot(out_path: str | Path, on_line: LineCallback = None,
             cfg: dict | None = None) -> ToolResult:
    """设备截图：snapshot_display 到临时目录 → hdc file recv 拉回。"""
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    code, out = hdc("shell", f"snapshot_display -f {REMOTE_SHOT}", cfg=cfg,
                    on_line=on_line, timeout=90)
    if code == 127:
        return ToolResult(False, out)
    if cancelled():
        return ToolResult(False, "已中断", detail=out[-1000:])
    code, out = hdc("file", "recv", REMOTE_SHOT, str(target), cfg=cfg,
                    on_line=on_line, timeout=120)
    if target.is_file() and target.stat().st_size > 0:
        return ToolResult(True, f"截图已保存（{target.stat().st_size:,} 字节）", artifact=str(target))
    return ToolResult(False, "截图失败（设备端可能不支持 snapshot_display）", detail=out[-1000:])


def tap(x: int, y: int, on_line: LineCallback = None, cfg: dict | None = None) -> ToolResult:
    code, out = hdc("shell", f"uitest uiInput click {int(x)} {int(y)}", cfg=cfg,
                    on_line=on_line, timeout=60)
    return ToolResult(code == 0, f"点击 ({x},{y})" if code == 0 else "点击失败", detail=out[-500:])


# ---------------------------------------------------------------- 一键巡检


def inspect(hap: str | Path, bundle: str, wait_seconds: float = 15.0,
            shots_dir: str | Path | None = None, tag: str = "last",
            taps: list[tuple[int, int]] | None = None, cfg: dict | None = None,
            install: bool = True, on_line: LineCallback = None) -> ToolResult:
    """一键巡检：装机 → 启动 → 等首帧 → 截图 →（可选）逐点点击并截图。

    返回的最后一张截图在 ToolResult.artifact。
    """
    if not find_hdc(cfg):
        return ToolResult(False, "未找到 hdc.exe：装机/截图都依赖它（设置 → 插件与依赖）")
    devices, _raw = list_targets(cfg=cfg, on_line=on_line)
    if not devices:
        return ToolResult(False, "没有可用设备（hdc list targets 为空）：请先连真机/模拟器")
    _emit(on_line, f"设备：{', '.join(d.serial for d in devices)}")

    out_dir = Path(shots_dir) if shots_dir else app_config.workspace_sub(
        app_config.load(), "shots")
    out_dir.mkdir(parents=True, exist_ok=True)

    if install:
        res = install_hap(hap, bundle, on_line=on_line, cfg=cfg)
        if not res.ok:
            return res
    started = start_app(bundle, on_line=on_line, cfg=cfg)
    if not started.ok:
        return started

    _emit(on_line, f"等待 {wait_seconds:.0f}s 让首帧/探针完成…")
    time.sleep(max(0.0, float(wait_seconds)))

    shot = snapshot(out_dir / f"dev_{tag}.jpeg", on_line=on_line, cfg=cfg)
    if not shot.ok:
        return shot
    last = shot.artifact
    for i, (x, y) in enumerate(taps or [], start=1):
        _emit(on_line, f"[巡检 {i}/{len(taps or [])}] 点击 ({x},{y})")
        tap(x, y, on_line=on_line, cfg=cfg)
        time.sleep(2.5)
        step_shot = snapshot(out_dir / f"dev_{tag}_t{i}.jpeg", on_line=on_line, cfg=cfg)
        if step_shot.ok:
            last = step_shot.artifact
    return ToolResult(True, f"巡检完成，共 {1 + len(taps or [])} 张截图", artifact=last)


# ---------------------------------------------------------------- 浏览器探针


def find_node() -> str:
    """找 node.exe（探针脚本用）。找不到返回空串。"""
    exe = shutil.which("node")
    if exe:
        return exe
    for cand in (Path("C:/Program Files/nodejs/node.exe"),
                 Path("C:/Program Files (x86)/nodejs/node.exe")):
        if cand.is_file():
            return str(cand)
    return ""


def probe_script_path() -> Path:
    """browser_probe.js 的位置。

    开发态直接用仓库里的 scripts/browser_probe.js；
    冻结态**不能**用包内临时目录——puppeteer-core 的 node_modules 得由用户装在
    脚本旁边，而 `_MEIPASS` 是每次启动都变的临时目录。所以冻结态像 apktool.jar
    一样把脚本解到 %LOCALAPPDATA%/WBox/tools/probe/，用户在那里 `npm i puppeteer-core`
    一次即可长期生效。
    """
    from wbox.paths import bundled_root, is_frozen, tools_dir

    if not is_frozen():
        return bundled_root() / "scripts" / "browser_probe.js"
    target_dir = tools_dir() / "probe"
    target = target_dir / "browser_probe.js"
    source = bundled_root() / "scripts" / "browser_probe.js"
    if not target.is_file() and source.is_file():
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        except OSError:
            return source          # 解不出来就退回包内路径，让 probe_status 去报原因
    return target


def _probe_node_modules() -> list[Path]:
    """puppeteer-core 只可能装在这几个 node_modules 里（Node 从脚本所在目录向上找）。"""
    here = probe_script_path().resolve().parent
    roots = [here, here.parent, here.parent.parent]
    return [r / "node_modules" / "puppeteer-core" for r in roots]


def probe_status(cfg: dict | None = None) -> tuple[bool, str]:
    """浏览器探针能不能跑？返回 (可用, 说明)。

    GUI 拿它决定按钮是亮是灰——缺什么说什么，绝不在点击后才报错。
    """
    node = find_node()
    if not node:
        return False, "需要 node.exe：未实现内置下载，请自行安装 Node.js"
    script = probe_script_path()
    if not script.is_file():
        return False, f"探针脚本缺失：{script}"
    if not any(p.is_dir() for p in _probe_node_modules()):
        return False, "需要 puppeteer-core：请在脚本同级目录执行 npm i puppeteer-core"
    edge = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
    if not edge.is_file():
        return False, "需要 Edge/Chromium：browser_probe.js 默认驱动 C:/Program Files (x86)/Microsoft/Edge"
    return True, f"node + puppeteer-core 就绪（{node}）"


def run_browser_probe(url: str, out_png: str | Path, mode: str = "normal",
                      viewport: str = "1280x586", dpr: float = 1.0,
                      on_line: LineCallback = None, timeout: int = 240) -> ToolResult:
    """用 Node 跑 browser_probe.js：对给定 URL 截图，供与真机逐像素比对。

    注意 argv 顺序是 <url> <mode> <out> [WxH] [dpr]（与 browser_probe.js 一致）——
    早期版本漏了 mode 参数，导致输出文件名被当成模式，务必别再省。
    mode: normal=WebGL 原样跑；canvas=拦掉 getContext('webgl') 强制回落 Canvas2D。
    """
    ok, why = probe_status()
    if not ok:
        return ToolResult(False, why)
    node = find_node()
    script = probe_script_path()
    if not url.strip():
        return ToolResult(False, "请填写要探测的页面 URL")
    target = Path(out_png)
    target.parent.mkdir(parents=True, exist_ok=True)
    code, out = run_cmd([node, str(script), url.strip(), mode, str(target), viewport, str(dpr)],
                        on_line=on_line, timeout=timeout)
    if code == 0 and target.is_file():
        renderer = ""
        for line in (out or "").splitlines():
            if '"renderer"' in line:
                renderer = line.strip().strip(",").split(":", 1)[-1].strip().strip('"')
                break
        note = f"（渲染器 {renderer}）" if renderer else ""
        return ToolResult(True, f"探针完成{note}", artifact=str(target), detail=out[-800:])
    return ToolResult(False, f"探针失败（退出码 {code}）", detail=out[-1500:])


def probe_pair(url: str, out_dir: str | Path, tag: str = "probe",
               viewport: str = "1280x586", dpr: float = 1.0,
               on_line: LineCallback = None) -> ToolResult:
    """同一 URL 跑 normal / canvas 两模式各一张图，用于"WebGL vs 回落"并排比对。"""
    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    results: list[ToolResult] = []
    for mode in ("normal", "canvas"):
        if cancelled():
            return ToolResult(False, "已中断")
        res = run_browser_probe(url, folder / f"{tag}-{mode}.png", mode=mode,
                                viewport=viewport, dpr=dpr, on_line=on_line)
        results.append(res)
        if not res.ok:
            return ToolResult(False, f"[{mode}] {res.message}", detail=res.detail)
    return ToolResult(
        True, "两模式探针完成（normal=WebGL，canvas=强制回落）",
        artifact=results[0].artifact,
        detail=f"canvas 图：{results[1].artifact}")


# ---------------------------------------------------------------- 本地静态服务


def ensure_static_server(root: str | Path, port: int = 0, prefer: int = 8791
                         ) -> tuple[object | None, str, str]:
    """起一个临时 `python -m http.server` 给探针用（H5 常常是相对路径，file:// 打不开）。

    返回 (server 对象, base_url, 说明)。端口冲突时自动顺延 10 次；全都占用就返回 None，
    由调用方把原因说给用户听——不要静默换端口让人猜。
    """
    import http.server
    import socketserver

    directory = str(Path(root))
    last_error = ""
    candidates = [prefer] + ([0] if port == 0 else [port]) + list(range(prefer + 1, prefer + 10))
    for cand in candidates:
        try:
            handler = functools.partial(
                http.server.SimpleHTTPRequestHandler, directory=directory)
            httpd = socketserver.ThreadingTCPServer(("127.0.0.1", cand), handler)
            httpd.daemon_threads = True
        except OSError as e:
            last_error = f"{e}"
            continue
        actual = int(httpd.server_address[1])
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        return httpd, f"http://127.0.0.1:{actual}/", f"本地静态服务已启动 {directory} → 端口 {actual}"
    return None, "", f"端口 {prefer}~{prefer + 9} 都被占用：{last_error}"


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="WBox 内置工具链")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("devices", help="列出已连接设备")
    p_build = sub.add_parser("build", help="编译鸿蒙工程")
    p_build.add_argument("project")
    p_install = sub.add_parser("install", help="安装 HAP")
    p_install.add_argument("hap")
    p_install.add_argument("--bundle", default="")
    p_shot = sub.add_parser("shot", help="设备截图")
    p_shot.add_argument("out")
    p_inspect = sub.add_parser("inspect", help="一键巡检")
    p_inspect.add_argument("--hap", required=True)
    p_inspect.add_argument("--bundle", required=True)
    p_inspect.add_argument("--wait", type=float, default=15.0)
    p_inspect.add_argument("--tag", default="cli")
    p_inspect.add_argument("--tap", action="append", default=[], help="x,y 可重复")
    args = parser.parse_args(argv)

    show = lambda line: print(line, flush=True)   # noqa: E731
    if args.cmd == "devices":
        exe = find_hdc()
        print(f"hdc: {exe or '（未找到）'}")
        devices, _ = list_targets(on_line=show)
        for d in devices:
            print(d.as_text())
        return 0 if devices else 1
    if args.cmd == "build":
        res = build_project(args.project, on_line=show)
        print(res.as_text())
        return 0 if res.ok else 1
    if args.cmd == "install":
        res = install_hap(args.hap, args.bundle, on_line=show)
        print(res.as_text())
        return 0 if res.ok else 1
    if args.cmd == "shot":
        res = snapshot(args.out, on_line=show)
        print(res.as_text())
        return 0 if res.ok else 1
    if args.cmd == "inspect":
        taps: list[tuple[int, int]] = []
        for item in args.tap:
            try:
                x, y = (int(v) for v in item.split(","))
                taps.append((x, y))
            except ValueError:
                print(f"跳过非法坐标：{item}")
        res = inspect(args.hap, args.bundle, wait_seconds=args.wait, tag=args.tag,
                      taps=taps, on_line=show)
        print(res.as_text())
        return 0 if res.ok else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
