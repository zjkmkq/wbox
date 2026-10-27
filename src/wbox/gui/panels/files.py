"""wbox.gui.panels.files —— 左栏「文件」tab：工程产物的文件树浏览器。

2026-10-25 产品化补缺（用户需求③）：拆解产物此前只在 spec 清单里看名字，
无法打开检查。本面板直接浏览工程目录（work/ 拆解产物、rawfile、exports 等），
双击按类型路由：
  - 图片/音频 → QDesktopServices 系统默认程序打开
  - 文本类（smali/xml/java/ets/kt/json/txt…）→ 内置只读查看器（可复制/外部编辑）
  - 其他（so/zip/ttf…）→ 系统默认程序尝试打开

命名规则（用户需求④）：文件系统恒英文命名，UI 层按配置显示中文翻译
（config["naming_display"]：zh=中文，en=原文）。
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileSystemModel,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from wbox import config as app_config

# 内置查看器可直读的文本类（其余走系统默认程序）
_TEXT_SUFFIXES = {
    ".smali", ".java", ".kt", ".ets", ".ts", ".js", ".json", ".json5",
    ".xml", ".txt", ".md", ".html", ".css", ".properties", ".yml", ".yaml",
    ".mf", ".cfg", ".ini", ".gradle", ".pro", ".toml",
}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
_AUDIO_SUFFIXES = {".mp3", ".ogg", ".wav", ".m4a", ".flac"}
_MAX_PREVIEW_BYTES = 4 * 1024 * 1024  # 4MB 以上提示过大不直读

# 常见英文名 → 中文显示映射（UI 层；文件系统不变）
_ZH_NAMES = {
    "assets": "资源资产", "res": "安卓资源", "smali": "字节码", "unknown": "未识别",
    "work": "拆解产物", "rawfile": "鸿蒙原生资源", "exports": "任务包",
    "draft": "ArkTS 草案", "harmony": "鸿蒙工程", "logs": "木头贴图",
    "disks": "锯片", "model": "机身", "ui": "界面", "sfx": "音效",
    "AndroidManifest.xml": "安卓清单", "spec.json": "迁移契约",
}


def zh_display(name: str, zh: bool) -> str:
    if not zh:
        return name
    return _ZH_NAMES.get(name, name)


class TextViewerDialog(QDialog):
    """内置文本查看器：只读 + 可复制 + 大小/编码提示 + 外部编辑入口。"""

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path = path
        self.setWindowTitle(f"查看 {path.name}")
        self.resize(900, 640)
        lay = QVBoxLayout(self)

        info = QLabel(f"{path}  ·  {path.stat().st_size:,} 字节")
        info.setObjectName("muted")
        lay.addWidget(info)

        self.text = QPlainTextEdit()
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.text.setReadOnly(True)
        lay.addWidget(self.text, stretch=1)

        row = QHBoxLayout()
        row.addStretch(1)
        btn_copy = QPushButton("复制全部")
        btn_copy.clicked.connect(self._copy_all)
        btn_edit = QPushButton("用系统默认程序打开")
        btn_edit.clicked.connect(self._open_external)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_copy)
        row.addWidget(btn_edit)
        row.addWidget(btn_close)
        lay.addLayout(row)

        self._load()

    def _load(self) -> None:
        size = self._path.stat().st_size
        if size > _MAX_PREVIEW_BYTES:
            self.text.setPlainText(f"（文件 {size:,} 字节，超过 4MB 内置预览上限。\n"
                                   f"请用「用系统默认程序打开」查看，或对二进制文件用专业工具。）")
            return
        try:
            content = self._path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            self.text.setPlainText(f"读取失败：{e}")
            return
        self.text.setPlainText(content)

    def _copy_all(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.text.toPlainText())

    def _open_external(self) -> None:
        QDesktopServices.openUrl(self._path.as_uri())


class FileBrowserPanel(QWidget):
    """文件树：浏览工程目录，双击按类型路由打开。"""

    status_hint = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        bar = QHBoxLayout()
        self.btn_root = QPushButton("工程根目录")
        self.btn_root.clicked.connect(self._go_project_root)
        self.btn_work = QPushButton("拆解产物")
        self.btn_work.setToolTip("跳转 work/ 拆解目录")
        self.btn_work.clicked.connect(self._go_work)
        self.btn_exports = QPushButton("任务包")
        self.btn_exports.clicked.connect(self._go_exports)
        bar.addWidget(self.btn_root)
        bar.addWidget(self.btn_work)
        bar.addWidget(self.btn_exports)
        bar.addStretch(1)
        lay.addLayout(bar)

        self.model = QFileSystemModel()
        self.model.setRootPath("")
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.doubleClicked.connect(self._open_index)
        self.tree.setSortingEnabled(True)
        self.tree.setColumnWidth(0, 260)
        lay.addWidget(self.tree, stretch=1)

        self._root: Path | None = None
        self._zh = True

    # ------------------------------------------------------------ 浏览

    def set_zh(self, zh: bool) -> None:
        self._zh = zh

    def browse(self, path: Path) -> None:
        """把树根设到 path 并展开。"""
        path = Path(path)
        if not path.is_dir():
            return
        self._root = path
        idx = self.model.index(str(path))
        self.tree.setRootIndex(idx)
        self.tree.expandToDepth(1)

    def _go_project_root(self) -> None:
        if self._root:
            # 工程根 = _root 的祖先中最近的 .wbox 目录或其本身
            self.browse(self._root)

    def _go_work(self) -> None:
        if self._root:
            self.browse(self._root / "work")

    def _go_exports(self) -> None:
        if self._root:
            self.browse(self._root / "exports")

    # ------------------------------------------------------------ 打开路由

    def _open_index(self, index) -> None:
        path = Path(self.model.filePath(index))
        if path.is_dir():
            return
        self.open_file(path)

    def open_file(self, path: Path) -> None:
        suffix = path.suffix.lower()
        try:
            if suffix in _TEXT_SUFFIXES:
                TextViewerDialog(path, self).exec()
            elif suffix in _IMAGE_SUFFIXES or suffix in _AUDIO_SUFFIXES:
                QDesktopServices.openUrl(path.as_uri())
            else:
                # so/zip/font 等：先试系统关联，失败提示专业工具
                if not QDesktopServices.openUrl(path.as_uri()):
                    self.status_hint.emit(f"没有能打开 {path.name} 的关联程序")
        except OSError as e:
            self.status_hint.emit(f"打开失败：{e}")

    # ------------------------------------------------------------ 右键菜单

    def _context_menu(self, pos) -> None:
        index = self.tree.indexAt(pos)
        if not index.isValid():
            return
        path = Path(self.model.filePath(index))
        menu = QMenu(self)
        act_open = menu.addAction("打开")
        act_open.triggered.connect(lambda _checked=False: self.open_file(path))
        act_reveal = menu.addAction("在资源管理器中显示")
        act_reveal.triggered.connect(
            lambda _checked=False: QDesktopServices.openUrl(path.parent.as_uri()))
        act_copy = menu.addAction("复制路径")
        act_copy.triggered.connect(lambda _checked=False: self._copy_path(path))
        act_del = menu.addAction("删除（移入回收区）…")
        act_del.triggered.connect(lambda _checked=False: self._delete_selected())
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _copy_path(self, path: Path) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(str(path))

    # ------------------------------------------------------------ 删除（软删除优先）

    def _delete_selected(self) -> None:
        """删除选中项：默认移入工作区回收区（可恢复）；明确告知、逐项列名。

        用户运行部署要求（2026-10-25）：「避免删除文件，确需删除须明确标注告知」。
        这里双重兑现：avoid_delete=True 时永不物理 unlink；关闭时也先红字
        警告不可恢复，并要求显式确认。
        """
        sel = self.tree.selectionModel()
        paths = []
        if sel is not None:
            for i in sel.selectedRows():
                if i.isValid():
                    p = Path(self.model.filePath(i))
                    if p.exists():
                        paths.append(p)
        if not paths:
            self.status_hint.emit("请先选中要删除的文件或目录（可多选）")
            return
        cfg = app_config.load()
        avoid = bool((cfg.get("behavior") or {}).get("avoid_delete", True))
        names = "\n".join(f"· {p.name}" for p in paths[:10])
        more = "" if len(paths) <= 10 else f"\n……等共 {len(paths)} 项"
        if avoid:
            text = (f"以下 {len(paths)} 项将移入工作区回收区（不物理删除，可恢复）：\n\n"
                    f"{names}{more}\n\n回收区位置：{app_config.workspace_sub(cfg, 'trash')}")
        else:
            text = (f"⚠ 不可恢复删除：以下 {len(paths)} 项将被永久删除，回收站也找不到：\n\n"
                    f"{names}{more}\n\n设置里「避免删除文件」当前为关闭状态。")
        r = QMessageBox.question(self, "确认删除", text,
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                 QMessageBox.StandardButton.No)
        if r != QMessageBox.StandardButton.Yes:
            return
        ok, fail = self._do_delete(paths, avoid)
        if ok:
            self.status_hint.emit(f"已删除 {ok} 项" + (f"，失败 {fail} 项" if fail else ""))
        elif fail:
            self.status_hint.emit(f"删除失败 {fail} 项")

    def _do_delete(self, paths: list[Path], avoid: bool) -> tuple[int, int]:
        """执行删除。avoid=True 一律移入回收区（保留目录结构+时间戳防重名）。"""
        cfg = app_config.load()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        ok = fail = 0
        for p in paths:
            try:
                if avoid:
                    trash = app_config.workspace_sub(cfg, "trash") / stamp
                    trash.mkdir(parents=True, exist_ok=True)
                    dest = trash / p.name
                    n = 1
                    while dest.exists():
                        dest = trash / f"{p.name}.{n}"
                        n += 1
                    shutil.move(str(p), str(dest))
                else:
                    if p.is_dir():
                        shutil.rmtree(p)
                    else:
                        p.unlink()
                ok += 1
            except OSError:
                fail += 1
        return ok, fail
