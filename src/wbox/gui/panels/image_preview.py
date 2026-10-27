"""wbox.gui.panels.image_preview —— 资源图片预览窗。

存在理由：资源栏只能看到文件名，用户"点开需求的资源检查"时无从判断这张图
是不是要迁的那张。本窗把图片本体 + 尺寸 + 体积 + 原始路径 + 迁移决策一次给全，
大图自适应缩放（KeepAspectRatio + SmoothTransformation），小图不拉伸。

离线/无 Qt 图片插件时也不崩：读不出来就明确显示"无法解码"，不静默空白。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QMovie, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from wbox.gui.uikit import harden_window, plain_text

_ICON_HINT = ("提示：滚轮（或 Ctrl+滚轮）缩放；双击画面切换 适应窗口 / 原始大小。")


class ImagePreviewDialog(QDialog):
    """单图预览：图片 + 元信息 + 缩放 + 定位到资源管理器。"""

    def __init__(self, path: str | Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path = Path(path)
        self._pixmap = QPixmap()
        self._movie: QMovie | None = None
        self._scale = 1.0
        self._fit = True

        self.setWindowTitle(f"预览图片 —— {self._path.name}")
        self.resize(900, 700)
        self.setMinimumSize(420, 360)

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        self.info = QLabel("")
        self.info.setObjectName("muted")
        lay.addWidget(self.info)

        self.canvas = QLabel()
        self.canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.canvas.setMinimumSize(120, 120)
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setWidget(self.canvas)
        self.area.setFrameShape(QScrollArea.Shape.NoFrame)
        lay.addWidget(self.area, stretch=1)

        hint = QLabel(_ICON_HINT)
        hint.setObjectName("muted")
        lay.addWidget(hint)

        bar = QHBoxLayout()
        self.btn_fit = QPushButton("适应窗口")
        self.btn_fit.clicked.connect(lambda: self._set_fit(True))
        self.btn_100 = QPushButton("原始大小")
        self.btn_100.clicked.connect(lambda: self._set_fit(False))
        self.btn_out = QPushButton("缩小 −")
        self.btn_out.clicked.connect(lambda: self._zoom(0.8))
        self.btn_in = QPushButton("放大 +")
        self.btn_in.clicked.connect(lambda: self._zoom(1.25))
        self.btn_reveal = QPushButton("在资源管理器中显示")
        self.btn_reveal.clicked.connect(self._reveal)
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.accept)
        for w in (self.btn_fit, self.btn_100, self.btn_out, self.btn_in):
            bar.addWidget(w)
        bar.addStretch(1)
        bar.addWidget(self.btn_reveal)
        bar.addWidget(self.btn_close)
        lay.addLayout(bar)

        self._load()
        harden_window(self)

    # ------------------------------------------------------------ 载入

    def _load(self) -> None:
        suffix = self._path.suffix.lower()
        ok = False
        if suffix == ".gif":
            # GIF 只取首帧（动图逐帧播放对资源核对没意义，还拖慢窗口）
            movie = QMovie(str(self._path))
            if movie.isValid():
                movie.jumpToFrame(0)
                self._pixmap = movie.currentPixmap()
                self._movie = movie
                ok = not self._pixmap.isNull()
        if not ok:
            self._pixmap = QPixmap(str(self._path))
            ok = not self._pixmap.isNull()

        size_text = "—"
        try:
            size_text = f"{self._path.stat().st_size:,} 字节"
        except OSError:
            size_text = "（文件不可读）"

        if not ok:
            self.info.setText(f"{self._path}  ·  {size_text}  ·  无法解码（Qt 无该格式插件或文件损坏）")
            self.info.setToolTip(self.info.text())
            self.canvas.setText("无法预览此图片")
            self.btn_fit.setEnabled(False)
            self.btn_100.setEnabled(False)
            self.btn_in.setEnabled(False)
            self.btn_out.setEnabled(False)
            return

        w = self._pixmap.width()
        h = self._pixmap.height()
        self.info.setText(
            f"{self._path.name}  ·  {w} × {h} px  ·  {size_text}  ·  {self._path.parent}")
        self.info.setToolTip(f"{self._path}\n{w} × {h} px，{size_text}")
        self._render()

    # ------------------------------------------------------------ 缩放

    def _set_fit(self, fit: bool) -> None:
        self._fit = fit
        if fit:
            self._scale = 1.0
        self._render()

    def _zoom(self, factor: float) -> None:
        self._fit = False
        self._scale = max(0.05, min(16.0, self._scale * factor))
        self._render()

    def _target_size(self):
        if self._pixmap.isNull():
            return None
        if self._fit:
            view = self.area.viewport().size()
            avail_w = max(80, view.width() - 8)
            avail_h = max(80, view.height() - 8)
            scaled = self._pixmap.scaled(
                avail_w, avail_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            # 不放大超过原图（小图放大只会糊）
            if scaled.width() > self._pixmap.width():
                return self._pixmap
            return scaled
        return self._pixmap.scaled(
            int(self._pixmap.width() * self._scale),
            int(self._pixmap.height() * self._scale),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _render(self) -> None:
        target = self._target_size()
        if target is None:
            return
        self.canvas.setPixmap(target)
        self.canvas.resize(target.size())
        if not self._fit:
            self.btn_100.setToolTip(f"当前缩放 {self._scale * 100:.0f}%")

    def resizeEvent(self, event) -> None:  # noqa: N802  Qt 命名
        super().resizeEvent(event)
        if self._fit:
            self._render()

    def wheelEvent(self, event) -> None:  # noqa: N802  Qt 命名
        delta = event.angleDelta().y()
        if delta == 0:
            return
        self._zoom(1.25 if delta > 0 else 0.8)
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802  Qt 命名
        self._set_fit(not self._fit)
        super().mouseDoubleClickEvent(event)

    # ------------------------------------------------------------ 外部

    def _reveal(self) -> None:
        QDesktopServices.openUrl(QUrl(self._path.parent.as_uri()))

    @property
    def plain_info(self) -> str:
        return plain_text(self.info.text())
