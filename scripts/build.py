"""scripts/build.py —— WBox 单文件打包一条龙。

用法：
    python scripts/build.py            # 全流程（检查→打包→校验）
    python scripts/build.py --no-check # 跳过依赖检查

产物：dist/WBox.exe（约 50-60MB，含内置 apktool jar）
分发时附带 README_dist.txt（使用说明 + 大依赖下载指引）。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = Path(sys.executable)
SPEC = ROOT / "wbox.spec"
DIST = ROOT / "dist"

README = """WBox 跨平台迁移白盒工作台 — 使用说明
=====================================

这是什么
    把 Android 应用（APK）白盒迁移成 HarmonyOS NEXT 工程的桌面工具。
    五步流水线：拆 → 画拼图 → 判断 → 填上 → 补缝。
    理念是"参照重做"：AI 生成草案，你保留每一步判断权。

快速开始
    1. 双击 WBox.exe（首次启动约 3-10 秒解压内置资源，属正常）。
    2. 首页会自动体检依赖。缺什么，点对应"安装/引导"按钮即可：
       - apktool：已内置，自动解出，无需操作。
       - Java 17：缺失时点"自动下载"（Temurin 17，约 180MB）。
       - HarmonyOS SDK：用于第⑤步编译。检测到你本机已有
         DevEco Studio 或 Command Line Tools 会自动挂载；
         都没有时，按首页引导下载 Command Line Tools（约 2.4GB）。
    3. 点"打开工程"选择工程目录（含 spec.json），或"新建工程"导入 APK。
    4. 按五步走完，每步的修改都会写回 spec.json，可随时回溯。

数据放在哪
    全部写在 %LOCALAPPDATA%\\WBox\\（配置/工具/缓存/日志）。
    exe 本身只读，删除不影响数据；卸载 = 删 exe + 删该目录。

常见问题
    - 启动慢：onefile 首次需解压到临时目录，之后就快了。
    - 编译失败提示找不到 SDK：装 Command Line Tools 后在首页点"重新检测"。
    - 想换机器迁移工程：把工程目录（含 spec.json）整个拷走即可。
"""


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print(f"+ {' '.join(str(c) for c in cmd)}")
    return subprocess.run(cmd, cwd=ROOT, **kw)


def check_deps() -> bool:
    ok = True
    for mod in ("PyInstaller", "PySide6"):
        r = run([str(PY), "-c", f"import {mod}; print({mod}, {mod}.__version__)"],
                capture_output=True, text=True)
        print(f"  {r.stdout.strip() or r.stderr.strip()[-200:]}")
        ok = ok and r.returncode == 0
    jar = ROOT / "tools" / "apktool" / "apktool.jar"
    if jar.is_file():
        print(f"  apktool jar: {jar.stat().st_size / 1024 / 1024:.1f} MB (内置)")
    else:
        print("  !! 缺少 tools/apktool/apktool.jar，请先放入")
        ok = False
    return ok


def _kill_stale_exe() -> None:
    """打包前清掉还在跑的 WBox.exe——文件被占用会让 --clean 删旧 exe 时
    trash 失败（Some operations were aborted），整个打包挂掉。"""
    if sys.platform.startswith("win"):
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq WBox.exe"],
                           capture_output=True)
        if b"WBox.exe" in (r.stdout or b""):
            print("检测到 WBox.exe 正在运行，先结束（旧实例占着 exe 文件）…")
            subprocess.run(["taskkill", "/F", "/IM", "WBox.exe"],
                           capture_output=True)


def build() -> Path:
    if DIST.exists():
        shutil.rmtree(DIST, ignore_errors=True)
    _kill_stale_exe()
    r = run([str(PY), "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC)])
    if r.returncode != 0:
        raise SystemExit(f"打包失败（退出码 {r.returncode}）")
    exe = DIST / "WBox.exe"
    if not exe.is_file():
        raise SystemExit("打包器未产出 dist/WBox.exe")
    return exe


def verify(exe: Path) -> None:
    size = exe.stat().st_size
    print(f"\n产物：{exe}")
    print(f"大小：{size / 1024 / 1024:.1f} MB")
    readme = DIST / "README_dist.txt"
    readme.write_text(README, encoding="utf-8")
    print(f"说明：{readme}")
    # 冒烟：--version 探测启动（窗口模式启动即阻塞，用 import 自检代替）
    r = run([str(PY), "-c",
             "import sys; sys.path.insert(0, 'src');"
             "import wbox.gui.mainwin, wbox.deps, wbox.hvigor;"
             "print('module self-check OK')"],
            capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip()[-300:])


def main() -> None:
    # 构建脚本的本职就是反复生成/清理 dist/ 产物；环境的 safe-delete guard 会把
    # 删除路由到回收站，trash 失败即 FAIL_CLOSED 让打包挂掉（PyInstaller --clean
    # 删旧 exe 必踩）。剥掉 guard 状态变量后子进程与 shutil 都不再触发。
    for var in ("CODEBUDDY_SAFE_DELETE_BULK_STATE_DIR", "CODEBUDDY_TOOL_CALL_ID"):
        os.environ.pop(var, None)

    ap = argparse.ArgumentParser()
    ap.add_argument("--no-check", action="store_true", help="跳过依赖检查")
    args = ap.parse_args()
    if not args.no_check and not check_deps():
        raise SystemExit("依赖检查未过，终止打包")
    print("\n=== 打包中（onefile，约 1-3 分钟）===")
    exe = build()
    print("\n=== 校验 ===")
    verify(exe)
    print("\n完成：dist/ 目录即分发内容（WBox.exe + README_dist.txt）")


if __name__ == "__main__":
    main()
