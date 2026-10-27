"""wbox.deps —— 依赖管理：检测 / 自动安装 / 状态报告。

定位（写死，不许绕）：
- 目标是"新设备下载即用"：应用自己检查全部依赖，小体积随身带（apktool jar
  打进 exe），大体积自己下（Command Line Tools 含 hvigorw+SDK、JDK17），
  已装的自动认（本机 DevEco Studio/PATH java）。
- 本模块只回答三个问题：缺什么（check_all）、怎么修（每项带 fix 动作）、
  现在装（install，带进度回调）。不 import GUI，CLI 可直接跑。

依赖清单：
  java      JDK 17+            apktool 解包必需         自动下载 Temurin 17
  apktool   apktool_2.11.x.jar 「拆」步引擎              内置（exe 解出）
  clt       Command Line Tools 「补缝」步编译（hvigor+SDK）自动下载（约 2.4GB）

CLI：
    python -m wbox.deps                 # 状态表
    python -m wbox.deps --install java  # 安装指定依赖
    python -m wbox.deps --install clt   # 大件，带进度
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from wbox import config as app_config
from wbox.paths import (
    apktool_jar_path,
    bundled_resource,
    clt_dir,
    jdk_dir,
    tools_dir,
)

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------- 数据结构


@dataclass
class DepStatus:
    id: str
    name: str
    purpose: str
    ok: bool
    location: str = ""
    version: str = ""
    fix: str = ""            # install / manual
    required: bool = True
    size_mb: float = 0.0
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "purpose": self.purpose,
            "ok": self.ok, "location": self.location, "version": self.version,
            "fix": self.fix, "required": self.required,
            "size_mb": self.size_mb, "detail": self.detail,
        }


@dataclass
class Toolchain:
    """编译工具链归一化结果（GUI/CLI 共用）。"""
    node: Path
    hvigorw: Path            # hvigorw.js
    sdk_home: Path
    source: str = ""         # config / auto / deveco

    def env(self) -> dict[str, str]:
        e = dict(os.environ)
        e["DEVECO_SDK_HOME"] = str(self.sdk_home)
        return e


@dataclass
class _InstallResult:
    ok: bool
    message: str = ""
    location: str = ""


# ---------------------------------------------------------------- 通用下载


def download_file(
    url: str,
    dest: Path,
    progress: Callable[[int, int], None] | None = None,
    timeout: int = 30,
    chunk_size: int = 1 << 20,
) -> int:
    """流式下载到 dest（先下 .part 再改名）。返回字节数。

    华为 CDN 对无 UA 的请求返回 403，必须带浏览器 UA。
    """
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    tmp = dest.with_suffix(dest.suffix + ".part")
    done = 0
    total = 0
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        with open(tmp, "wb") as f:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    tmp.replace(dest)
    return done


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _extract_zip(zip_path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(dest)


def _extract_targz(tar_path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "r:gz") as t:
        t.extractall(dest)


def _run_quiet(cmd: list[str], timeout: int = 20) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return p.returncode, p.stdout or "", p.stderr or ""
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, "", str(e)


# ---------------------------------------------------------------- java


def java_bin(cfg: dict | None = None) -> str:
    """解析 java 可执行：配置的 java_home > PATH。"""
    cfg = cfg or app_config.load()
    home = cfg.get("tools", {}).get("java_home", "")
    if home:
        cand = Path(home)
        if cand.is_dir():
            exe = "java.exe" if sys.platform.startswith("win") else "java"
            direct = cand / "bin" / exe
            if direct.exists():
                return str(direct)
            if cand.name == "bin":
                maybe = cand / exe
                if maybe.exists():
                    return str(maybe)
        elif cand.exists():
            return str(cand)
    return "java"


def check_java(cfg: dict | None = None) -> DepStatus:
    exe = java_bin(cfg)
    code, out, err = _run_quiet([exe, "-version"])
    text = (out + err).strip()
    ver = ""
    m = re.search(r'version "([^"]+)"', text)
    if m:
        ver = m.group(1)
    ok = code == 0 and ver != ""
    # JDK 17+ 才算满足（apktool 2.11 与 hvigor 均要求现代 JDK）
    major = 0
    m2 = re.match(r"(\d+)", ver)
    if m2:
        major = int(m2.group(1))
        if major == 1 and "." in ver:  # 1.8 形式
            major = int(ver.split(".")[1])
    if ok and major < 17:
        ok = False
    return DepStatus(
        id="java", name="Java 运行时 (JDK 17+)",
        purpose="apktool 解包 APK 必需；hvigor 签名任务亦需要",
        ok=ok, location=exe if ok else "", version=ver,
        fix="" if ok else "install", size_mb=180.0,
        detail="" if ok else ("版本过低（需 17+）：" + ver if ver else "未检测到 java，需安装 JDK 17"),
    )


def install_java(progress: Callable[[int, int], None] | None = None) -> _InstallResult:
    """下载 Temurin JDK 17（Adoptium API 直链）并解压到 tools/jdk。"""
    if not sys.platform.startswith("win"):
        return _InstallResult(False, "自动安装 JDK 目前仅支持 Windows；请手动安装 JDK 17+ 并在设置里指定 java_home")
    url = ("https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/"
           "jdk/hotspot/normal/eclipse")
    dest_dir = jdk_dir()
    zip_path = tools_dir() / "jdk17-download.zip"
    try:
        download_file(url, zip_path, progress=progress, timeout=60)
    except (urllib.error.URLError, OSError) as e:
        return _InstallResult(False, f"下载失败：{e}")
    try:
        _extract_zip(zip_path, dest_dir)
    finally:
        zip_path.unlink(missing_ok=True)
    # 解压后应存在单个 jdk-17.x 目录
    subs = [p for p in dest_dir.iterdir() if p.is_dir() and (p / "bin").is_dir()]
    if not subs:
        return _InstallResult(False, "解压完成但未找到 JDK 目录")
    return _InstallResult(True, location=str(subs[0]))


# ---------------------------------------------------------------- apktool


def _apktool_candidates(cfg: dict) -> list[Path]:
    cands: list[Path] = []
    configured = cfg.get("tools", {}).get("apktool_jar", "")
    if configured:
        cands.append(Path(configured))
    cands.append(apktool_jar_path())                       # 自动安装/内置解出位置
    cands.append(bundled_resource("tools", "apktool", "apktool.jar"))
    legacy = bundled_resource("wbox.config.json")
    if legacy.exists():
        try:
            data = json.loads(legacy.read_text(encoding="utf-8"))
            jar = data.get("tools", {}).get("apktool", {}).get("jar", "")
            if jar:
                cands.append(Path(jar))
        except (json.JSONDecodeError, OSError):
            pass
    cands.extend(sorted(Path("D:/tools/apktool").glob("apktool*.jar")) if Path("D:/tools/apktool").is_dir() else [])
    return cands


def apktool_jar(cfg: dict | None = None) -> str:
    for c in _apktool_candidates(cfg or app_config.load()):
        if c.is_file():
            return str(c)
    return ""


def check_apktool(cfg: dict | None = None) -> DepStatus:
    jar = apktool_jar(cfg)
    if not jar:
        return DepStatus(
            id="apktool", name="apktool 2.11+", purpose="「拆」步：APK 解包出资源与 smali",
            ok=False, fix="install", size_mb=24.5,
            detail="未找到 apktool jar（应随应用内置，异常）",
        )
    java = java_bin(cfg)
    code, out, err = _run_quiet([java, "-jar", jar, "--version"], timeout=60)
    ver = (out + err).strip().splitlines()[-1] if (out + err).strip() else ""
    ok = code == 0
    if ok:
        return DepStatus(
            id="apktool", name="apktool 2.11+", purpose="「拆」步：APK 解包出资源与 smali",
            ok=True, location=jar, version=ver,
        )
    # jar 在位但跑不动：先分清是 java 没就绪还是 jar 真异常。
    # java 缺失时 fix 不能是 manual（jar 是内置的，让用户去设置里指定是错引导），
    # 应提示"装好 Java 自动可用"，由 Java 行的一键安装解决
    jcode, _, _ = _run_quiet([java, "-version"])
    if jcode != 0:
        return DepStatus(
            id="apktool", name="apktool 2.11+", purpose="「拆」步：APK 解包出资源与 smali",
            ok=False, fix="", size_mb=24.5,
            detail="jar 已内置；安装上方 Java 17 后自动可用",
        )
    return DepStatus(
        id="apktool", name="apktool 2.11+", purpose="「拆」步：APK 解包出资源与 smali",
        ok=False, fix="manual", size_mb=24.5,
        detail=f"jar 存在且 java 正常，但运行失败：{ver[:120]}",
    )


def install_apktool() -> _InstallResult:
    """把内置 jar 解出到 tools/（开发态下从仓库 tools/ 或 D:\\tools 复制）。"""
    target = apktool_jar_path()
    if target.is_file():
        return _InstallResult(True, location=str(target))
    src = bundled_resource("tools", "apktool", "apktool.jar")
    if src.is_file():
        shutil.copyfile(src, target)
        return _InstallResult(True, location=str(target))
    # 开发态兜底：本机 D:\tools
    d = Path("D:/tools/apktool")
    if d.is_dir():
        for jar in sorted(d.glob("apktool*.jar")):
            shutil.copyfile(jar, target)
            return _InstallResult(True, location=str(target))
    return _InstallResult(False, "未找到内置 apktool jar")


# ---------------------------------------------------------------- Command Line Tools

# GitHub 镜像仓库：跟踪官方 Command Line Tools 全版本直下地址 + sha256
_CLT_REPO = "hhtczengjing/ohos_command_line_tools"
# 官网直链可能过期，内置一个已验证可用的稳定版兜底（2026-04 发布）
_CLT_PINNED = {
    "version": "6.1.0.830",
    "packageName": "commandline-tools-windows-x64-6.1.0.830.zip",
    "downloadUrl": (
        "https://contentcenter-vali-drcn.dbankcdn.cn/pvt_2/DeveloperAlliance_package_901_9/"
        "69/v3/X1DieXs4Tg-MQnHGtVJbsA/commandline-tools-windows-x64-6.1.0.830.zip"
    ),
    "sha256": "010b52dc776c354a865d464fe734447dde7b57d942c80dff48cafad3f551efcc",
    "packageSize": 2599585816,
}

_DEVECO_CANDIDATES = [
    Path("C:/Program Files/Huawei/DevEco Studio"),
    Path("C:/Program Files (x86)/Huawei/DevEco Studio"),
    Path("D:/Office_Tools/DevEco Studio"),
    Path("D:/DevEco Studio"),
    Path("C:/DevEco Studio"),
    Path.home() / "AppData" / "Local" / "Huawei" / "DevEco Studio",
]


def _clt_roots(cfg: dict) -> list[Path]:
    roots: list[Path] = []
    configured = cfg.get("tools", {}).get("command_line_tools", "")
    if configured:
        p = Path(configured)
        roots.extend([p, p / "command-line-tools"])
    roots.append(clt_dir())
    roots.extend(_DEVECO_CANDIDATES)
    return roots


_VERSION_DIR_RE = re.compile(r"^\d+\.\d+\.\d+")


def _sdk_home_valid(p: Path) -> bool:
    """p 是否是 hvigor 能用的 SDK 根。

    判据来自 hvigor-ohos-plugin 的 HosLocalComponentLoader 源码（2026-10-24 实测）：
    扫描器只认 `sdk-pkg.json` 清单，且组件所在目录必须叫 `default`（或与
    pathVersionMapper 生成的期望目录同名）。因此：
      <root>/default/sdk-pkg.json                 ← DevEco Studio 内置 SDK（本机唯一可用）
      <root>/<version>/sdk-pkg.json + ets/         ← 部分命令行工具包布局
    注意：`DevEco Studio Sdk/OpenHarmony SDK/26.0.0/` 这种独立 SDK 只有组件级
    oh-uni-package.json、没有 sdk-pkg.json，hvigor 扫出零组件 → 00303312，不可用。
    """
    if not p.is_dir():
        return False
    if (p / "default" / "sdk-pkg.json").is_file():
        return True
    try:
        for child in p.iterdir():
            if child.is_dir() and (child / "sdk-pkg.json").is_file() and (child / "ets").is_dir():
                return True
    except OSError:
        return False
    return False


def _probe_sdk_root(p: Path) -> Path | None:
    """p 是否包含 hvigor 可用的 SDK（可经 OpenHarmony SDK 中转一层）。

    兼容布局：
      <sdk-root>/default/sdk-pkg.json              （IDE 内置 SDK 根）
      <sdk-root>/26.0.0/ets/...                     （命令行工具包，需 sdk-pkg.json）
      <sdk-root>/OpenHarmony SDK/<上述>              （DevEco Studio 安装中转）
    """
    if not p.is_dir():
        return None
    if _sdk_home_valid(p):
        return p
    oh = p / "OpenHarmony SDK"
    if oh.is_dir():
        found = _probe_sdk_root(oh)
        return found or None
    return None


def _probe_clt_root(root: Path) -> Toolchain | None:
    """探测一个根是否是可用的 hvigor+SDK 工具链。

    兼容两种布局：
      command-line-tools 包：<root>/bin/hvigorw  <root>/node/bin/node  <root>/sdk
      DevEco Studio 安装：  <root>/tools/hvigor/bin/hvigorw.js  <root>/tools/node/node.exe
                              SDK 在 <studio名> Sdk/OpenHarmony SDK/<版本> 或 DEVECO_SDK_HOME
    """
    # command-line-tools 布局
    for base in (root, root / "command-line-tools"):
        hvigorw = base / "bin" / "hvigorw"
        hvigorw_js = base / "bin" / "hvigorw.js"
        node = base / "node" / "bin" / ("node.exe" if sys.platform.startswith("win") else "node")
        sdk = base / "sdk"
        if (hvigorw.exists() or hvigorw_js.exists()) and node.exists() and sdk.is_dir():
            return Toolchain(node=node, hvigorw=hvigorw_js if hvigorw_js.exists() else hvigorw,
                             sdk_home=sdk, source="auto")
    # DevEco Studio 布局
    hvigorw_js = root / "tools" / "hvigor" / "bin" / "hvigorw.js"
    node = root / "tools" / "node" / ("node.exe" if sys.platform.startswith("win") else "node")
    if hvigorw_js.exists() and node.exists():
        # 优先级（2026-10-24 实测确定）：IDE 内置 SDK（sdk/default/sdk-pkg.json）
        # > DEVECO_SDK_HOME > 独立 SDK（DevEco Studio Sdk/...，多为不可用布局）
        candidates: list[Path] = [root / "sdk"]
        sdk_env = os.environ.get("DEVECO_SDK_HOME", "")
        if sdk_env:
            candidates.append(Path(sdk_env))
        candidates.append(root.parent / (root.name + " Sdk"))
        try:
            candidates.extend(sorted(root.parent.glob("*[Ss]dk*")))
        except OSError:
            pass
        for cand in candidates:
            sdk = _probe_sdk_root(cand)
            if sdk:
                return Toolchain(node=node, hvigorw=hvigorw_js, sdk_home=sdk, source="deveco")
    return None


def resolve_toolchain(cfg: dict | None = None) -> Toolchain | None:
    for root in _clt_roots(cfg or app_config.load()):
        try:
            tc = _probe_clt_root(root)
        except OSError:
            tc = None
        if tc:
            return tc
    return None


def check_clt(cfg: dict | None = None) -> DepStatus:
    tc = resolve_toolchain(cfg)
    if tc:
        return DepStatus(
            id="clt", name="HarmonyOS 命令行工具链",
            purpose="「补缝」步：hvigorw 编译 ArkTS 工程 + SDK",
            ok=True, location=str(tc.hvigorw.parent), version=tc.source,
            detail=f"node={tc.node} | sdk={tc.sdk_home}",
        )
    return DepStatus(
        id="clt", name="HarmonyOS 命令行工具链",
        purpose="「补缝」步：hvigorw 编译 ArkTS 工程 + SDK",
        ok=False, fix="install", size_mb=2465.0,
        detail="未找到 Command Line Tools / DevEco Studio；编译验证不可用",
    )


def _fetch_clt_catalog() -> dict:
    """从 GitHub 镜像仓库取最新稳定版目录条目（失败则用内置兜底）。"""
    api = f"https://api.github.com/repos/{_CLT_REPO}/contents/versions"
    try:
        req = urllib.request.Request(api, headers={"User-Agent": BROWSER_UA})
        with urllib.request.urlopen(req, timeout=20) as resp:
            entries = json.loads(resp.read().decode("utf-8"))
        names = [e["name"] for e in entries if e["name"].endswith(".json")]
        # 版本号降序，跳过 Beta
        def keyf(n: str) -> tuple:
            try:
                return tuple(int(x) for x in n[:-5].split("."))
            except ValueError:
                return (0,)
        for name in sorted(names, key=keyf, reverse=True):
            entry_url = f"https://api.github.com/repos/{_CLT_REPO}/contents/versions/{name}"
            try:
                req = urllib.request.Request(entry_url, headers={"User-Agent": BROWSER_UA})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                import base64
                payload = json.loads(base64.b64decode(data["content"]).decode("utf-8"))
            except (urllib.error.URLError, OSError, ValueError, KeyError):
                continue
            if "beta" in payload.get("versionName", "").lower():
                continue
            plat = payload.get("platforms", {}).get("windows-x64") if sys.platform.startswith("win") \
                else payload.get("platforms", {}).get("linux-x86")
            if plat and plat.get("downloadUrl"):
                return {
                    "version": payload.get("buildVersion", name[:-5]),
                    "packageName": plat["packageName"],
                    "downloadUrl": plat["downloadUrl"],
                    "sha256": plat.get("sha256", ""),
                    "packageSize": int(plat.get("packageSize", 0)),
                }
    except (urllib.error.URLError, OSError, ValueError):
        pass
    return dict(_CLT_PINNED)


def install_clt(progress: Callable[[int, int], None] | None = None) -> _InstallResult:
    """下载并解压 Command Line Tools 到 tools/command-line-tools。"""
    if not sys.platform.startswith("win"):
        return _InstallResult(False, "自动安装命令行工具目前仅支持 Windows；请手动下载并在设置里指定目录")
    cat = _fetch_clt_catalog()
    dest_dir = clt_dir()
    zip_path = tools_dir() / cat["packageName"]
    if not zip_path.exists():
        try:
            download_file(cat["downloadUrl"], zip_path, progress=progress, timeout=60)
        except (urllib.error.URLError, OSError) as e:
            return _InstallResult(False, f"下载失败：{e}")
    if cat.get("sha256"):
        got = sha256_file(zip_path)
        if got.lower() != cat["sha256"].lower():
            zip_path.unlink(missing_ok=True)
            return _InstallResult(False, "sha256 校验失败，安装包可能损坏，已删除重试")
    try:
        _extract_zip(zip_path, dest_dir)
    finally:
        zip_path.unlink(missing_ok=True)
    tc = _probe_clt_root(dest_dir)
    if not tc:
        return _InstallResult(False, "解压完成但未探测到 hvigorw/SDK，请检查解压目录")
    return _InstallResult(True, location=str(dest_dir))


# ---------------------------------------------------------------- 汇总

_INSTALLERS: dict[str, Callable[..., _InstallResult]] = {
    "java": install_java,
    "apktool": install_apktool,
    "clt": install_clt,
}


def check_all(cfg: dict | None = None) -> list[DepStatus]:
    cfg = cfg or app_config.load()
    return [check_java(cfg), check_apktool(cfg), check_clt(cfg)]


def install(dep_id: str, progress: Callable[[int, int], None] | None = None) -> _InstallResult:
    fn = _INSTALLERS.get(dep_id)
    if not fn:
        return _InstallResult(False, f"未知依赖：{dep_id}")
    try:
        return fn(progress=progress) if dep_id != "apktool" else fn()
    except Exception as e:  # 安装过程任何异常都不许崩掉 GUI
        return _InstallResult(False, f"安装过程出错：{e}")


# ---------------------------------------------------------------- CLI


def _fmt_size(mb: float) -> str:
    if mb >= 1024:
        return f"{mb / 1024:.1f} GB"
    return f"{mb:.0f} MB"


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="WBox 依赖检测与安装")
    parser.add_argument("--install", metavar="DEP", help="安装指定依赖：java/apktool/clt")
    args = parser.parse_args(argv)

    if args.install:
        def show(done: int, total: int) -> None:
            if total:
                pct = done * 100 // total
                print(f"\r下载中 {pct}% ({done / 1048576:.0f}/{total / 1048576:.0f} MB)", end="", flush=True)
        r = install(args.install, progress=show if args.install != "apktool" else None)
        print()
        print(("成功：" + r.location) if r.ok else ("失败：" + r.message))
        return 0 if r.ok else 1

    cfg = app_config.load()
    print(f"数据目录：{tools_dir().parent}")
    print(f"{'依赖':<14}{'状态':<6}{'版本/位置'}")
    print("-" * 72)
    for d in check_all(cfg):
        mark = "OK" if d.ok else "缺失"
        info = d.version or d.location or d.detail
        print(f"{d.name:<14}{mark:<6}{info[:80]}")
        if not d.ok:
            print(f"{'':14}修复：{'一键安装' if d.fix == 'install' else '手动配置'}"
                  f"（约 {_fmt_size(d.size_mb)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
