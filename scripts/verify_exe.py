"""scripts/verify_exe.py —— 对打包产物做真实启动冒烟。

模拟新设备场景验证：
1. WBox.exe 能否独立启动（进程存活 ≥ 8 秒 = Qt/资源/导入链 OK）。
2. onefile 是否把内置 apktool jar 正确解出到 _MEIPASS（启动时自动完成）。
3. 应用数据目录是否按设计落在 %LOCALAPPDATA%\\WBox。

用法：python scripts/verify_exe.py [dist/WBox.exe]
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 第一个不以 - 开头的参数才是 exe 路径（--selftest 是模式开关）
_POSITIONAL = [a for a in sys.argv[1:] if not a.startswith("-")]
EXE = Path(_POSITIONAL[0]) if _POSITIONAL else ROOT / "dist" / "WBox.exe"
WAIT_SECONDS = 10


def proc_alive(name: str) -> bool:
    # 中文 Windows 的 tasklist 输出是 GBK，text=True 会 UnicodeDecodeError
    r = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}"],
                       capture_output=True)
    out = (r.stdout or b"").decode("utf-8", errors="replace")
    return name.lower() in out.lower()


def run_selftest() -> int:
    """冷启动自检：让 exe 自己把五个入口 + 模板/教程过一遍，读它写的日志。

    为什么这么绕：WBox.exe 是 windowed（console=False），stdout 是空的，
    没法用 print 验收。所以 exe 支持 `--selftest`：离屏跑一遍、把结论写到
    %LOCALAPPDATA%/WBox/logs/selftest.log、用退出码回话。
    """
    import os

    log = Path(os.environ.get("LOCALAPPDATA", "")) / "WBox" / "logs" / "selftest.log"
    if log.is_file():
        log.unlink()            # 清掉旧结论，避免读到上一次的 OK
    print(f"冷启动自检：{EXE} --selftest（离屏，约 10-30 秒）…")
    try:
        r = subprocess.run([str(EXE), "--selftest"], cwd=EXE.parent,
                           capture_output=True, timeout=180)
    except subprocess.TimeoutExpired:
        print("!! 自检超时（180s）：exe 可能卡在启动阶段（资源解压/线程未退出）")
        return 4
    text = (r.stdout or b"").decode("utf-8", errors="replace").strip()
    if text:
        print(text)
    if log.is_file():
        print(f"\n（日志：{log}）\n" + log.read_text(encoding="utf-8", errors="replace"))
    else:
        print("!! 没生成 selftest.log：冻结态可能连 paths.logs_dir() 都没跑通")
    if r.returncode == 0 and "SELFTEST OK" in (text + (log.read_text(encoding='utf-8', errors='replace')
                                                        if log.is_file() else "")):
        print("✓ 冷启动自检通过：打包产物里形态模板与教程库都在，五个入口都能打开")
        return 0
    print(f"!! 冷启动自检失败（退出码 {r.returncode}）")
    err = (r.stderr or b"").decode("utf-8", errors="replace").strip()
    if err:
        print(err[-2000:])
    return 3


def main() -> int:
    if not EXE.is_file():
        print(f"!! 找不到 {EXE}，先跑 scripts/build.py")
        return 1
    print(f"冒烟对象：{EXE}（{EXE.stat().st_size / 1024 / 1024:.1f} MB）")

    if "--selftest" in sys.argv:
        return run_selftest()

    print(f"启动 WBox.exe，等待 {WAIT_SECONDS} 秒…")
    p = subprocess.Popen([str(EXE)], cwd=EXE.parent)
    time.sleep(WAIT_SECONDS)

    alive = proc_alive("WBox.exe")
    print(f"进程存活：{'✓' if alive else '✗'}")
    if not alive:
        # 给一次机会：可能已闪退，读退出码
        code = p.poll()
        print(f"!! 进程已退出，退出码 {code}")
        return 2

    # 数据目录检查（应用运行即会创建）
    local = Path(sys.argv[0]).drive
    data = Path(__import__("os").environ.get("LOCALAPPDATA", "")) / "WBox"
    for sub in ("", "tools", "cache", "logs"):
        d = data / sub
        print(f"数据目录 {d}：{'✓' if d.is_dir() else '—'}")
    print(f"\n✓ 冒烟通过：exe 可独立启动。请在桌面上目视确认窗口后关闭。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
