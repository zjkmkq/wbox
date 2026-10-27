"""wbox.gui.webview —— 内嵌浏览器（QtWebEngine）+ 必须存在的降级路径。

存在理由：帮助中心"本地查不到就联网"。联网有两种做法：
  A. 内嵌 WebEngine 显示 Bing 结果（体验好，但重、且在某些环境里会黑屏/崩溃）
  B. 直接用系统浏览器打开（永远可用）

产品要求是 A，但**A 不许成为单点故障**。所以本模块只做一件事：先探测能不能用
WebEngine；能用就内嵌，不能就退成 B，并把真实原因写在界面上（不静默失败、不空白）。

探测口径（写死）：
- `QT_QPA_PLATFORM=offscreen`（离屏冒烟/CI）→ 视为不可用，绝不实例化 WebEngine
- import PySide6.QtWebEngineWidgets 失败 → 不可用
- 环境变量 WBOX_NO_WEBENGINE=1 → 强制关闭（用户排障用）
- 真正创建时抛异常 → 本次降级，并在进程内记住不再尝试
"""

from __future__ import annotations

import os
from urllib.parse import quote

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from wbox.gui.uikit import harden_window

SEARCH_ENGINE_NAME = "Bing"


def bing_url(query: str) -> str:
    """Bing 检索地址（quote 一次，避免中文/特殊符号把 URL 打断）。"""
    return f"https://www.bing.com/search?q={quote(str(query or '').strip())}"


def webengine_available() -> bool:
    """当前环境能否安全创建 QtWebEngine 视图。"""
    if os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen":
        return False
    if os.environ.get("WBOX_NO_WEBENGINE", "") in ("1", "true", "yes"):
        return False
    if getattr(webengine_available, "_broken", False):
        return False
    try:
        import PySide6.QtWebEngineWidgets  # noqa: F401  仅探测可导入性
    except Exception:  # noqa: BLE001  ImportError / 缺 DLL 都算不可用
        webengine_available._broken = True   # type: ignore[attr-defined]
        return False
    return True


def unavailable_reason() -> str:
    """给人看的不可用原因（界面要显示，不能只留空白）。"""
    if os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen":
        return "离屏模式不加载内嵌浏览器"
    if os.environ.get("WBOX_NO_WEBENGINE", "") in ("1", "true", "yes"):
        return "已通过 WBOX_NO_WEBENGINE 关闭内嵌浏览器"
    if getattr(webengine_available, "_broken", False):
        return "当前环境缺少 QtWebEngine 运行时（已自动降级为系统浏览器）"
    return "内嵌浏览器不可用"


class OnlineSearchDialog(QDialog):
    """联网检索窗：优先内嵌 Bing，不可用时降级为「用系统浏览器打开」。"""

    def __init__(self, query: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._query = str(query or "").strip()
        self._url = bing_url(self._query)
        self.setWindowTitle(f"联网检索 —— {self._query or '(空)'}")
        self.resize(980, 720)
        self.setMinimumSize(560, 420)

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        self.info = QLabel("")
        self.info.setObjectName("muted")
        lay.addWidget(self.info)

        self.view = None
        self._fallback = None
        if webengine_available():
            try:
                from PySide6.QtWebEngineWidgets import QWebEngineView

                view = QWebEngineView(self)
                view.setUrl(QUrl(self._url))
                self.view = view
                lay.addWidget(view, stretch=1)
            except Exception:  # noqa: BLE001  创建崩溃/缺 DLL：本次降级
                webengine_available._broken = True   # type: ignore[attr-defined]
                self.view = None
        if self.view is None:
            self._fallback = self._build_fallback()
            lay.addWidget(self._fallback, stretch=1)
            self.info.setText(f"内嵌浏览器不可用：{unavailable_reason()}。"
                              f"下面给出 {SEARCH_ENGINE_NAME} 检索地址，可一键用系统浏览器打开。")
        else:
            self.info.setText(f"已在窗口内打开 {SEARCH_ENGINE_NAME} 检索：{self._query}")

        bar = QHBoxLayout()
        self.edit_url = QLineEdit(self._url)
        self.edit_url.setReadOnly(True)
        bar.addWidget(self.edit_url, stretch=1)
        btn_open = QPushButton("用系统浏览器打开")
        btn_open.clicked.connect(self._open_external)
        bar.addWidget(btn_open)
        if self.view is not None:
            btn_reload = QPushButton("重新加载")
            btn_reload.clicked.connect(self.view.reload)
            bar.addWidget(btn_reload)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        bar.addWidget(btn_close)
        lay.addLayout(bar)

        harden_window(self)

    def _build_fallback(self) -> QWidget:
        wrap = QWidget()
        inner = QVBoxLayout(wrap)
        inner.setContentsMargins(16, 16, 16, 16)
        inner.setSpacing(10)
        title = QLabel(f"要查的内容：{self._query or '(空)'}")
        title.setObjectName("h2")
        inner.addWidget(title)
        hint = QLabel(
            "本机帮助中心没有命中，可以直接在搜索引擎里查。\n"
            f"点击下面按钮会把 {SEARCH_ENGINE_NAME} 检索结果在你的系统浏览器里打开"
            "（不内嵌、不占内存，也不会上传本工作台的任何数据）。")
        hint.setObjectName("muted")
        inner.addWidget(hint)
        btn = QPushButton(f"在 {SEARCH_ENGINE_NAME} 搜索「{self._query}」")
        btn.setObjectName("primary")
        btn.clicked.connect(self._open_external)
        inner.addWidget(btn)
        inner.addStretch(1)
        return wrap

    def _open_external(self) -> None:
        QDesktopServices.openUrl(QUrl(self._url))

    @property
    def url(self) -> str:
        return self._url
