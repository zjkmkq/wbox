"""wbox.plugins —— 插件与依赖目录（设置 →「插件与依赖」页的唯一数据源）。

存在理由：依赖体检原本散落在首页 home.py 里，缺失项与"可选增强件"混在一起，
既占首屏又说不清"哪些必须装、哪些按需装"。本模块把依赖抽象成统一目录
（必需组 / 可选组），回答四个问题：

  - 有哪些条目（catalog，带用途/体积/主页）
  - 现在状态如何（已装→版本+位置；缺失→原因）
  - 能不能自动装（installable；不支持安装的显式给出官网链接，由 GUI 禁用按钮）
  - 现在装（install，带进度回调；先测网络再动手）

必需件复用 wbox.deps（java / apktool / HarmonyOS SDK / hvigor / jadx），
可选件走 pip（Pillow / fonttools）或标注"未实现自动安装"。
不 import GUI，CLI 可直接跑：`python -m wbox.plugins`。
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from wbox import deps

# ---------------------------------------------------------------- 数据结构


@dataclass
class PluginItem:
    """目录里的一项「插件/依赖」。"""

    id: str
    name: str
    purpose: str
    required: bool = True
    size_mb: float = 0.0
    homepage: str = ""
    ok: bool = False
    version: str = ""
    location: str = ""
    detail: str = ""
    installable: bool = True
    install_note: str = ""      # 不可自动安装时给用户的明确说明（不许装作能用）
    group: str = "required"     # required / optional

    @property
    def size_text(self) -> str:
        if self.size_mb <= 0:
            return "—"
        if self.size_mb >= 1024:
            return f"{self.size_mb / 1024:.1f} GB"
        return f"{self.size_mb:.0f} MB"

    @property
    def status_text(self) -> str:
        return "已就绪" if self.ok else ("缺失" if self.required else "未安装")

    def as_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "purpose": self.purpose,
            "required": self.required, "size_mb": self.size_mb, "homepage": self.homepage,
            "ok": self.ok, "version": self.version, "location": self.location,
            "detail": self.detail, "installable": self.installable,
            "install_note": self.install_note, "group": self.group,
        }


@dataclass
class InstallResult:
    ok: bool
    message: str = ""
    location: str = ""


# ---------------------------------------------------------------- 网络


_NET_PROBES: tuple[tuple[str, int], ...] = (
    ("mirrors.aliyun.com", 443),
    ("pypi.org", 443),
    ("github.com", 443),
)


def network_available(timeout: float = 3.0) -> bool:
    """联网可用性探测：任一常用源能连上即认为有网（3 秒超时，不卡 UI）。

    只做 TCP 握手，不发业务请求——探测本身必须便宜且无副作用。
    """
    for host, port in _NET_PROBES:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def network_summary(timeout: float = 3.0) -> tuple[bool, str]:
    """返回 (是否有网, 人话说明)。"""
    for host, port in _NET_PROBES:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True, f"已联网（{host}:{port} 可达）"
        except OSError:
            continue
    return False, "未联网（镜像源 / PyPI / GitHub 均不可达），安装按钮暂不可用"


# ---------------------------------------------------------------- 可选件（pip）

_PIP_PACKAGES: dict[str, tuple[str, str, str, float]] = {
    # id: (显示名, pip 包名, 用途, 体积MB)
    "pillow": ("Pillow（图像处理）", "Pillow",
               "图片批处理：资源图的缩放 / 压缩 / 格式转换，资源栏大图预览的备用解码", 3.0),
    "fonttools": ("fontTools（字体工具）", "fonttools",
                  "字体子集化与检查：把超大字体裁到实际用到的字形，减小 HAP 体积", 12.0),
}


def _pip_module_of(pid: str) -> str:
    """pip 包名 → import 名（用于检测是否已装）。"""
    return {"pillow": "PIL", "fonttools": "fontTools"}.get(pid, pid)


def _check_pip_item(pid: str) -> PluginItem:
    name, pkg, purpose, size = _PIP_PACKAGES[pid]
    item = PluginItem(
        id=pid, name=name, purpose=purpose, required=False, size_mb=size,
        group="optional", homepage=f"https://pypi.org/project/{pkg}/",
    )
    if getattr(sys, "frozen", False):
        # 打包版没有可用 pip：明确告知，而不是点了才报错
        item.installable = False
        item.install_note = "打包版暂不支持在线安装 Python 包（未实现），请用源码版或手动 pip 安装"
    import importlib.util

    spec = importlib.util.find_spec(_pip_module_of(pid))
    if spec is None:
        item.detail = "未安装（可选增强件）"
        return item
    item.ok = True
    item.location = str(Path(spec.origin).parent) if spec.origin else ""
    try:
        mod = importlib.import_module(_pip_module_of(pid))
        item.version = str(getattr(mod, "__version__", "") or "")
    except Exception:  # noqa: BLE001  版本探测失败不影响状态判定
        item.version = ""
    item.version = item.version or "已安装"
    return item


def _install_pip_item(pid: str, progress: Callable[[int, int], None] | None = None) -> InstallResult:
    _, pkg, _, _ = _PIP_PACKAGES[pid]
    if getattr(sys, "frozen", False):
        return InstallResult(False, "打包版不支持 pip 安装，请在源码环境执行：pip install " + pkg)
    cmd = [sys.executable, "-m", "pip", "install", "-U", pkg]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                              errors="replace")
    except (OSError, subprocess.SubprocessError) as e:
        return InstallResult(False, f"pip 调用失败：{e}")
    if progress:
        progress(1, 1)
    if proc.returncode != 0:
        tail = (proc.stdout or "") + (proc.stderr or "")
        return InstallResult(False, f"pip 安装失败（退出码 {proc.returncode}）：{tail[-400:]}")
    return InstallResult(True, location=pkg)


# ---------------------------------------------------------------- jadx（可选但常用）

_JADX_API = "https://api.github.com/repos/skylot/jadx/releases/latest"


def _check_jadx() -> PluginItem:
    item = PluginItem(
        id="jadx", name="jadx（DEX → Java 反编译）", required=True, size_mb=45.0,
        purpose="把 smali / dex 反读成近似 Java，用于「判断」步确认原逻辑意图",
        homepage="https://github.com/skylot/jadx/releases",
    )
    exe = shutil.which("jadx")
    if exe:
        item.ok = True
        item.location = exe
        item.version = "已安装"
        return item
    from wbox.paths import tools_dir

    local = tools_dir() / "jadx" / "bin" / "jadx.bat"
    if local.is_file():
        item.ok = True
        item.location = str(local)
        item.version = "已安装"
        return item
    item.detail = "未安装；装后「判断」步可直接读 Java 形态的代码，减少猜 smali"
    return item


def _install_jadx(progress: Callable[[int, int], None] | None = None) -> InstallResult:
    """下载 jadx 最新 release（windows zip）并解到 tools/jadx。"""
    if not sys.platform.startswith("win"):
        return InstallResult(False, "自动安装 jadx 目前仅支持 Windows（未实现其他平台）")
    import json
    import urllib.error
    import urllib.request

    from wbox.paths import tools_dir

    try:
        req = urllib.request.Request(_JADX_API, headers={"User-Agent": deps.BROWSER_UA})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        asset = next((a for a in data.get("assets", [])
                      if str(a.get("name", "")).endswith(".zip")
                      and "no-jre" not in str(a.get("name", ""))), None)
        if asset is None:
            return InstallResult(False, "未找到 jadx 的 Windows 压缩包，请到 GitHub Releases 手动下载")
        url = asset["browser_download_url"]
        name = asset["name"]
    except (urllib.error.URLError, OSError, ValueError, KeyError, StopIteration) as e:
        return InstallResult(False, f"获取 jadx 下载地址失败：{e}")

    tools = tools_dir()
    zip_path = tools / name
    try:
        deps.download_file(url, zip_path, progress=progress, timeout=60)
        deps._extract_zip(zip_path, tools / "jadx")
    except (urllib.error.URLError, OSError) as e:
        return InstallResult(False, f"下载/解压失败：{e}")
    finally:
        zip_path.unlink(missing_ok=True)
    exe = tools / "jadx" / "bin" / "jadx.bat"
    if not exe.is_file():
        return InstallResult(False, "解压完成但未找到 jadx.bat，结构可能已变化")
    return InstallResult(True, location=str(exe))


# ---------------------------------------------------------------- 必需件（复用 deps）


def _check_sdk(cfg: dict | None = None) -> PluginItem:
    """HarmonyOS SDK（hvigor 能扫到组件的那一份）。"""
    item = PluginItem(
        id="sdk", name="HarmonyOS SDK", required=True, size_mb=2465.0,
        purpose="「补缝」步编译 ArkTS 工程所依赖的 SDK 组件（ets/API）",
        homepage="https://developer.huawei.com/consumer/cn/deveco-studio/",
    )
    tc = deps.resolve_toolchain(cfg)
    if tc is None:
        item.detail = "未找到可用 SDK；安装命令行工具后自动就绪"
        return item
    item.ok = True
    item.location = str(tc.sdk_home)
    item.version = tc.sdk_home.name or "已就绪"
    item.detail = f"来源：{tc.source}"
    return item


def _check_hvigor(cfg: dict | None = None) -> PluginItem:
    """hvigor 构建器（随命令行工具或 DevEco Studio 提供）。"""
    item = PluginItem(
        id="hvigor", name="hvigor 构建器", required=True, size_mb=0.0,
        purpose="鸿蒙工程打包 HAP 的构建器，与 SDK 同一套命令行工具提供",
        homepage="https://developer.huawei.com/consumer/cn/deveco-studio/",
    )
    tc = deps.resolve_toolchain(cfg)
    if tc is None or not Path(tc.hvigorw).exists():
        item.detail = "未找到 hvigorw；安装命令行工具后自动就绪"
        return item
    item.ok = True
    item.location = str(tc.hvigorw)
    item.version = "已就绪"
    return item


def _from_dep(status: deps.DepStatus) -> PluginItem:
    return PluginItem(
        id=status.id, name=status.name, purpose=status.purpose, required=True,
        size_mb=status.size_mb, ok=status.ok, version=status.version,
        location=status.location, detail=status.detail,
        installable=bool(status.fix == "install"),
        install_note="" if status.fix == "install" else "请在「高级 → 工具路径」中手动指定",
        group="required",
    )


def _check_hdc(cfg: dict | None = None) -> PluginItem:
    """hdc：真机装机/截图用的设备桥（随命令行工具 / DevEco Studio 提供）。"""
    item = PluginItem(
        id="hdc", name="hdc（设备调试桥）", required=False, size_mb=0.0, group="optional",
        purpose="真机装机 / 截屏 / 取日志；「工具」页的装机与截图依赖它",
        homepage="https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/hdc",
        installable=False,
        install_note="未实现单独自动安装：装 HarmonyOS 命令行工具（含 SDK）后通常自带",
    )
    # 与「工具箱」页共用同一套查找逻辑（wbox.toolchain.find_hdc），
    # 避免两处口径不一致出现"插件页说缺、工具页能用"的自相矛盾
    from wbox import toolchain as toolchain_mod

    exe = toolchain_mod.find_hdc(cfg)
    if exe:
        item.ok = True
        item.location = exe
        item.version = "随 SDK 提供" if "toolchains" in exe.lower() else "已安装"
        return item
    item.detail = "未安装；装命令行工具后通常自带"
    return item


def _check_aapt2() -> PluginItem:
    """aapt2：APK 资源表分析（明确标注未实现自动安装，GUI 侧按钮禁用）。"""
    item = PluginItem(
        id="aapt2", name="aapt2（APK 资源表分析）", required=False, size_mb=0.0,
        group="optional",
        purpose="读取 APK 的 resources.arsc，辅助核对资源 id 与配置限定符",
        homepage="https://developer.android.com/tools/aapt2",
        installable=False,
        install_note="未实现自动安装：请从 Android SDK Build Tools 获取后，在「高级 → 工具路径」指定",
    )
    exe = shutil.which("aapt2")
    if exe:
        item.ok = True
        item.location = exe
        item.version = "已安装"
        return item
    item.detail = "未安装（可选；不影响主线迁移流程）"
    return item


# ---------------------------------------------------------------- 目录


def catalog(cfg: dict | None = None) -> list[PluginItem]:
    """完整目录：先必需组（缺一样主线就跑不动），后可选组（按需装）。

    注意：本函数会 spawn 子进程（java -version / apktool --version），
    GUI 侧必须放后台线程，不要在 UI 线程直接调。
    """
    cfg = cfg or deps.app_config.load()
    items: list[PluginItem] = [
        _from_dep(deps.check_java(cfg)),
        _from_dep(deps.check_apktool(cfg)),
        _check_jadx(),
        _check_sdk(cfg),
        _check_hvigor(cfg),
    ]
    items.extend([
        _check_pip_item("pillow"),
        _check_pip_item("fonttools"),
        _check_hdc(cfg),
        _check_aapt2(),
    ])
    return items


def missing_required(cfg: dict | None = None) -> list[PluginItem]:
    """必需组里未就绪的项（首页轻量提示用）。"""
    return [i for i in catalog(cfg) if i.required and not i.ok]


# ---------------------------------------------------------------- 安装

# id -> 实际安装器；sdk/hvigor 共用 clt 安装包（一次下载同时满足两者）
_INSTALLERS: dict[str, Callable[..., InstallResult]] = {
    "java": lambda progress=None: deps.install("java", progress=progress),
    "apktool": lambda progress=None: deps.install("apktool"),
    "clt": lambda progress=None: deps.install("clt", progress=progress),
    "sdk": lambda progress=None: deps.install("clt", progress=progress),
    "hvigor": lambda progress=None: deps.install("clt", progress=progress),
    "jadx": _install_jadx,
    "pillow": _install_pip_item,
    "fonttools": _install_pip_item,
}


def install(pid: str, progress: Callable[[int, int], None] | None = None,
            cfg: dict | None = None) -> InstallResult:
    """安装目录项。先测网络（离线直接失败，不浪费用户时间），再调安装器。

    任何异常都转成 InstallResult(False, ...)，绝不向上抛——GUI 不能因为
    一次下载失败就崩。
    """
    fn = _INSTALLERS.get(pid)
    if fn is None:
        return InstallResult(False, f"该条目未实现自动安装：{pid}")
    if not network_available():
        return InstallResult(False, "未联网：请先连网再安装（离线时安装按钮不可用）")
    try:
        return fn(progress=progress)
    except Exception as e:  # noqa: BLE001
        return InstallResult(False, f"安装过程出错：{e}")


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="WBox 插件与依赖目录")
    parser.add_argument("--install", metavar="ID", help="安装目录项：java/apktool/sdk/hvigor/jadx/pillow/fonttools")
    args = parser.parse_args(argv)

    if args.install:
        def show(done: int, total: int) -> None:
            if total:
                print(f"\r下载中 {done * 100 // total}% ({done / 1048576:.0f}/{total / 1048576:.0f} MB)",
                      end="", flush=True)
        r = install(args.install, progress=show)
        print()
        print(("成功：" + r.location) if r.ok else ("失败：" + r.message))
        return 0 if r.ok else 1

    online, note = network_summary()
    print(note)
    print(f"{'分组':<8}{'条目':<26}{'状态':<8}{'体积':<10}{'版本/位置'}")
    print("-" * 88)
    for it in catalog():
        group = "必需" if it.required else "可选"
        info = it.version or it.location or it.detail
        print(f"{group:<8}{it.name[:24]:<26}{it.status_text:<8}{it.size_text:<10}{info[:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
