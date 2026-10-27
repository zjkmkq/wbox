"""verify_device.py —— 把「装包 → 启动 → 等画面 → 截图 → 拉回」做成一键，供白盒校验用。

为什么需要它（2026-10-26 教训）：
    以前每一轮验证都靠人手动装包、人眼看屏、人嘴描述现象，一次往返十分钟，
    而且描述会失真（"一坨蓝色带花" 到底是空画布还是渲染错，光靠嘴说不清）。
    这个脚本把设备侧变成可编程的：截图直接落盘，可以逐像素比对参考图。

用法：
    python scripts/verify_device.py                      # 用默认 hap + 默认包名
    python scripts/verify_device.py --wait 18 --tag v2   # 自定义等待与截图标签
    python scripts/verify_device.py --no-install         # 只重启截图，不重装
    python scripts/verify_device.py --tap 637,1158 --tap 1416,1158
                                                         # 点一串坐标，每点一次截一张图
                                                         # （用于巡检设置/商店/成就等页面）

产物：
    D:/harmony/_shots/dev_<tag>.jpeg        设备整屏
    D:/harmony/_shots/dev_<tag>_t<N>.jpeg   第 N 次点击后的整屏

    --bundle 用于同时装「破解版」和「正常版」两份共存：默认包名是破解版，
    装正常版时传 --bundle com.webdevbrian.skipthestone.normal。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

HDC = Path(r"D:\Office_Tools\DevEco Studio\sdk\default\openharmony\toolchains\hdc.exe")
DEFAULT_HAP = Path(
    r"D:\harmony\SkipTheStone\entry\build\default\outputs\default\entry-default-unsigned.hap"
)
BUNDLE = "com.webdevbrian.skipthestone"
OUT_DIR = Path(r"D:\harmony\_shots")
REMOTE_DIR = "/data/local/tmp"


def hdc(*args: str, timeout: int = 120) -> str:
    """跑一条 hdc 命令，返回合并输出；不因非零退出码抛异常（hdc 经常返回非零但成功）。"""
    proc = subprocess.run(
        [str(HDC), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    return (proc.stdout or "") + (proc.stderr or "")


def install(hap: Path, bundle: str = BUNDLE) -> None:
    if not hap.exists():
        raise SystemExit(f"HAP 不存在：{hap}")
    remote = f"{REMOTE_DIR}/wbox-verify.hap"
    print(f"[1/5] 推送 {hap.name} ({hap.stat().st_size:,} 字节)")
    print(hdc("file", "send", str(hap), remote).strip())
    print(f"[2/5] 安装（bundleName={bundle}）")
    print(hdc("shell", f"bm install -p {remote}").strip())


def restart(wait: float, tag: str, bundle: str = BUNDLE) -> Path:
    print(f"[3/5] 重启应用（bundleName={bundle}）")
    hdc("shell", f"aa force-stop {bundle}")
    time.sleep(1)
    hdc("shell", f"aa start -a EntryAbility -b {bundle}")
    print(f"[4/5] 等待 {wait}s 让首帧与探针完成")
    time.sleep(wait)
    return snapshot(tag)


def snapshot(tag: str, suffix: str = "") -> Path:
    remote_png = f"{REMOTE_DIR}/wbox-shot.jpeg"
    hdc("shell", f"snapshot_display -f {remote_png}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    local = OUT_DIR / f"dev_{tag}{suffix}.jpeg"
    hdc("file", "recv", remote_png, str(local))
    print(f"      截图：{local.name} ({local.stat().st_size:,} 字节)" if local.exists() else "      截图失败")
    return local


def tour(tag: str, taps: list[str], settle: float) -> None:
    """依次点击坐标，每次点完截一张图。坐标是设备像素（2832x1280 这类实际分辨率）。"""
    for i, item in enumerate(taps, start=1):
        try:
            x, y = (int(v) for v in item.split(","))
        except ValueError:
            print(f"      跳过非法坐标：{item}")
            continue
        print(f"[tour {i}/{len(taps)}] 点击 ({x},{y})")
        hdc("shell", f"uitest uiInput click {x} {y}")
        time.sleep(settle)
        snapshot(tag, f"_t{i}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hap", default=str(DEFAULT_HAP))
    ap.add_argument("--bundle", default=BUNDLE,
                    help="包名；装「正常版」时传 com.webdevbrian.skipthestone.normal")
    ap.add_argument("--wait", type=float, default=14.0)
    ap.add_argument("--tag", default="last")
    ap.add_argument("--no-install", action="store_true")
    ap.add_argument("--tap", action="append", default=[], help="x,y —— 可重复，按顺序点击并截图")
    ap.add_argument("--settle", type=float, default=2.5, help="每次点击后等待秒数")
    args = ap.parse_args()

    if not HDC.exists():
        raise SystemExit(f"找不到 hdc：{HDC}")
    targets = hdc("list", "targets").strip()
    if not targets or "Empty" in targets:
        raise SystemExit("没有可用设备（hdc list targets 为空）")
    print(f"设备：{targets}")

    if not args.no_install:
        install(Path(args.hap), args.bundle)
    restart(args.wait, args.tag, args.bundle)
    if args.tap:
        tour(args.tag, args.tap, args.settle)
    return 0


if __name__ == "__main__":
    sys.exit(main())
