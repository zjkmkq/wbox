"""wbox.hvigor —— 「补缝」步编译验证：定位工具链 → 跑 assembleHap → 收日志。

硬规则（写死，不许绕）：
1. 工具链解析只认 deps.resolve_toolchain（配置 > 自动安装 > 本机 DevEco），
   本模块不自己猜路径。
2. 编译为子进程流式执行，日志逐行回调；HAP  unsigned 是正常的（签名归
   DevEco IDE），本模块只报 BUILD SUCCESSFUL/FAILED 与产物路径。
3. 结果由调用方写 build_log（经 wbox.spec），本模块不碰 spec。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from wbox import deps as dep_mod

_VERSION_DIR_RE = re.compile(r"^\d+\.\d+\.\d+")


def detect_sdk_version(sdk_home: Path) -> str:
    """取 SDK 的平台版本号（如 26.0.0）。

    优先读 default/sdk-pkg.json 的 platformVersion（IDE 内置 SDK 布局，
    没有版本目录名）；退回最高版本目录名（命令行工具包布局）。
    """
    pkg = sdk_home / "default" / "sdk-pkg.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8")).get("data", {})
            pv = str(data.get("platformVersion", "")).strip()
            if pv:
                return pv
        except (json.JSONDecodeError, OSError):
            pass
    versions = [c.name for c in sdk_home.iterdir()
                if c.is_dir() and _VERSION_DIR_RE.match(c.name)]
    if not versions:
        return ""
    return max(versions, key=lambda v: tuple(int(x) for x in v.split(".")))


def sync_sdk_versions(project_dir: str | Path, sdk_version: str) -> str:
    """把工程 build-profile.json5 的 SDK 版本对齐到工具链实际版本。

    这是 DevEco IDE「一键修正」的自动化：工程模板写的 5.0.0(12) 在只装了
    26.0.0 SDK 的机器上必然 00303312。原文件留 .bak。
    返回空串=无需修改。
    """
    bp = Path(project_dir) / "build-profile.json5"
    if not bp.is_file() or not sdk_version:
        return ""
    text = bp.read_text(encoding="utf-8")
    new = re.sub(r'("targetSdkVersion"\s*:\s*)"[^"]*"', rf'\1"{sdk_version}"', text)
    new = re.sub(r'("compatibleSdkVersion"\s*:\s*)"[^"]*"', rf'\1"{sdk_version}"', new)
    if new == text:
        return ""
    backup = bp.with_suffix(".json5.bak")
    if not backup.exists():
        backup.write_text(text, encoding="utf-8")
    bp.write_text(new, encoding="utf-8")
    return f"build-profile.json5 SDK 版本已对齐到 {sdk_version}（原文件留 .bak）"


@dataclass
class BuildResult:
    ok: bool
    summary: str = ""
    hap_path: str = ""
    log_tail: str = ""
    error: str = ""


def _find_hap(project_dir: Path) -> str:
    """在工程输出目录里找最大的那个 .hap（unsigned 亦可）。"""
    candidates: list[Path] = []
    for base in (project_dir / "entry" / "build" / "default" / "outputs" / "default",
                 project_dir / "build" / "outputs" / "default"):
        if base.is_dir():
            candidates.extend(base.glob("*.hap"))
    if not candidates:
        for p in project_dir.rglob("*.hap"):
            candidates.append(p)
    if not candidates:
        return ""
    return str(max(candidates, key=lambda p: p.stat().st_size))


_SUCCESS_RE = re.compile(r"BUILD SUCCESSFUL", re.I)
_FAILED_RE = re.compile(r"BUILD FAILED|ERROR:", re.I)


def run_build(
    project_dir: str | Path,
    on_line=None,
    cfg: dict | None = None,
    timeout: int = 900,
) -> BuildResult:
    """对鸿蒙工程跑 assembleHap。工程目录需含 build-profile.json5/hvigorw。"""
    project = Path(project_dir)
    if not (project / "build-profile.json5").exists():
        return BuildResult(False, error=f"不是鸿蒙工程目录（缺 build-profile.json5）：{project}")

    tc = dep_mod.resolve_toolchain(cfg)
    if tc is None:
        return BuildResult(False, error="未找到命令行工具链（hvigorw+SDK）：请到首页依赖体检安装")

    # 工程模板 SDK 版本与工具链不一致时自动对齐（IDE 一键修正的自动化）
    sdk_version = detect_sdk_version(tc.sdk_home)
    sync_note = sync_sdk_versions(project, sdk_version)
    if sync_note and on_line:
        on_line(sync_note)

    env = tc.env()
    # node 目录进 PATH，hvigorw.js 内部可能再调 node
    env["PATH"] = str(tc.node.parent) + os.pathsep + env.get("PATH", "")

    cmd = [str(tc.node), str(tc.hvigorw),
           "--mode", "module", "-p", "module=entry@default", "-p", "product=default",
           "-p", "requiredDeviceType=phone", "assembleHap",
           "--analyze=normal", "--no-daemon"]
    if on_line:
        on_line(" ".join(cmd))
    lines: list[str] = []
    try:
        proc = subprocess.Popen(cmd, cwd=str(project), env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace", bufsize=1)
    except OSError as e:
        return BuildResult(False, error=f"无法启动 hvigorw：{e}")
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            line = line.rstrip()
            lines.append(line)
            if on_line:
                on_line(line)
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        return BuildResult(False, error=f"编译超时（{timeout}s）", log_tail="\n".join(lines[-30:]))

    tail = "\n".join(lines[-40:])
    # 成功判定以 hvigor 自己打的 BUILD SUCCESSFUL 为准，不唯退出码：
    # 沙箱环境末尾拦截 wmic.exe 会让退出码非零，但 HAP 已产出。
    if _SUCCESS_RE.search(tail):
        hap = _find_hap(project)
        summary = "hvigor assembleHap BUILD SUCCESSFUL"
        if hap:
            size = Path(hap).stat().st_size
            summary += f"；HAP {size:,} 字节（unsigned，签名归 DevEco IDE）"
        elif code != 0:
            return BuildResult(False, error=f"编译日志报告成功但找不到 HAP 产物（退出码 {code}）",
                               log_tail=tail)
        return BuildResult(True, summary=summary, hap_path=hap, log_tail=tail)
    return BuildResult(False, error=f"编译失败（退出码 {code}）", log_tail=tail)


def append_build_log(session, module_id: str, result: BuildResult, action: str = "compile_verified") -> None:
    """把编译结果写进 spec.build_log 并落盘（调用方已持有 session）。"""
    entry = {
        "id": session.next_id("build_log", "log_"),
        "module_id": module_id,
        "action": action if result.ok else "runtime_fixed",
        "at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(timespec="seconds"),
        "summary": result.summary if result.ok else f"编译失败：{result.error}",
        "diff_ref": result.hap_path,
    }
    session.spec.setdefault("build_log", []).append(entry)
    session.save("编译记录")


def main(argv: list[str] | None = None) -> int:
    """CLI：python -m wbox.hvigor <工程目录> —— 流式编译并打印结果。"""
    import argparse

    parser = argparse.ArgumentParser(
        prog="wbox-hvigor", description="补缝：对鸿蒙工程跑 assembleHap 编译验证")
    parser.add_argument("project", help="鸿蒙工程根目录（含 build-profile.json5）")
    args = parser.parse_args(argv)

    r = run_build(args.project, on_line=lambda ln: print(ln))
    if r.ok:
        print(f"=== 编译通过 === {r.summary}")
        if r.hap_path:
            print(f"HAP: {r.hap_path}")
        return 0
    print(f"=== 编译失败 === {r.error}", file=sys.stderr)
    if r.log_tail:
        print(r.log_tail[-2000:], file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
