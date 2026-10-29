# -*- mode: python ; coding: utf-8 -*-
"""WBox 单文件打包规格（Windows 优先，跨平台可复用）。

设计原则（对应用户分发诉求）：
1. onefile + windowed：交付单个 WBox.exe，双击即用，无控制台黑窗。
2. 小体积依赖随身带：apktool jar（24.5MB）打进 exe，首次使用解出到
   %LOCALAPPDATA%/WBox/tools/，实现"下载即用"。
3. 大体积依赖（JDK 17、DevEco SDK / Command Line Tools）不打进包，
   由应用启动时自动检测，缺则首页引导一键安装。
4. 数据目录规则不变：可写数据只落 %LOCALAPPDATA%/WBox，exe 本身只读。

用法：
    pyinstaller --noconfirm --clean wbox.spec
"""

import os
from pathlib import Path

block_cipher = None

APP_NAME = "WBox"
APP_VERSION = "0.2.0"

# 瘦身开关（2026-10-27）：内嵌 Bing 帮助面板要带 QtWebEngine，实测把单文件 exe 从
# ~56MB 推到 ~236MB。设置 WBOX_SLIM=1 可打不含 WebEngine 的瘦身版——帮助中心会自动
# 降级为"用系统浏览器打开"（gui/webview.py 的既有降级路径），功能不缺，只是不内嵌。
SLIM = os.environ.get("WBOX_SLIM", "") == "1"
if SLIM:
    APP_NAME = "WBox-slim"

# 仓库根：PyInstaller 执行 spec 时注入 SPECPATH；兜底取 cwd/spec 文件位置
try:
    ROOT = Path(SPECPATH).resolve()
except NameError:
    ROOT = Path(os.path.abspath(__file__)).parent if "__file__" in dir() else Path.cwd()
SRC = ROOT / "src"

# ---------------------------------------------------------------- 数据文件
# (源路径, 包内目标目录)
datas = [
    (str(ROOT / "tools" / "apktool" / "apktool.jar"), "tools/apktool"),
    (str(ROOT / "spec.schema.json"), "."),
    (str(ROOT / "spec.example.json"), "."),
    # 鸿蒙工程骨架模板（assemble.py 装配用）：entry/build-profile.json5 等
    # 漏一个就 00304056/00304004，打包时容易忘——2026-10-24 实测踩坑
    (str(ROOT / "src" / "wbox" / "templates" / "harmony"), "wbox/templates/harmony"),
    # 形态模板库（wbox.shape 诊断仪用）与教程库（wbox.tutorial 帮助中心用）：
    # 目标目录必须与 shape.py / tutorial.py 里 Path(__file__).parent 的拼法一致，
    # 否则冻结态下诊断仪与帮助中心会同时变空——2026-10-27 加，改路径时两处一起改
    (str(ROOT / "src" / "wbox" / "shapes"), "wbox/shapes"),
    (str(ROOT / "src" / "wbox" / "tutorials"), "wbox/tutorials"),
    # 浏览器探针脚本（工具页「⑥ 浏览器探针」用）：冻结态由 toolchain 解到
    # %LOCALAPPDATA%/WBox/tools/probe/，用户在那里 npm i puppeteer-core 即可
    (str(ROOT / "scripts" / "browser_probe.js"), "scripts"),
]

# ---------------------------------------------------------------- 分析
a = Analysis(
    [str(SRC / "wbox" / "gui" / "__main__.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=(
        [
            # jsonschema 动态加载的格式检查器
            "jsonschema",
            "jsonschema.validators",
            # PySide6 插件由 PyInstaller hook 自动处理，这里兜底常用模块
            "PySide6.QtCore",
            "PySide6.QtGui",
            "PySide6.QtWidgets",
            "PySide6.QtNetwork",
        ]
        + ([] if SLIM else [
            # 帮助中心的联网检索（内嵌 Bing）：运行时导入，静态分析看不到
            "PySide6.QtWebEngineWidgets",
            "PySide6.QtWebEngineCore",
            "PySide6.QtWebChannel",
            "PySide6.QtPrintSupport",
        ])
    ),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=(
        [
            # 桌面应用用不到的 Qt 模块，砍体积
            # 注意：QtWebEngine 系列**默认不排除**——帮助中心联网检索要用它；
            # 只有显式 WBOX_SLIM=1 时才连带排除（届时联网检索退化为系统浏览器）
            "Qt3DCore",
            "Qt3DRender",
            "QtQuick",
            "QtQml",
            "QtMultimedia",
            "QtMultimediaWidgets",
            "QtBluetooth",
            "QtNfc",
            "QtSerialPort",
            "QtTest",
            "tkinter",
            "matplotlib",
            "numpy",
            "PIL",
        ]
        + (["PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineCore",
            "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel"] if SLIM else [])
    ),
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,               # windowed：无控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,                   # 暂无图标资源；补 ico 时在此填入路径即可
    version_info={
        "file_version": APP_VERSION.replace(".", ",") + ",0",
        "product_version": APP_VERSION.replace(".", ",") + ",0",
        "product_name": APP_NAME,
        "file_description": "跨平台迁移白盒工作台 — Android → HarmonyOS 参照重做流水线",
        "legal_copyright": "WBox Project",
    },
)
