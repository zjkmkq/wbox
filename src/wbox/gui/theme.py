"""wbox.gui.theme —— 双主题（深色 IDE / 浅色经典白）集中调色与 QSS。

色板来源：`D:/Game/GC/code/src/tailwind-theme.css`（hsl(222 30% 7%) 深空蓝底 +
hsl(172 65% 48%) 青绿 primary）。所有 Python 侧用色统一从本模块的语义常量取，
禁止在业务代码里写死 hex——换肤只改这一处。

双主题实现：一份 QSS 模板 + 两套调色板（dark/light）。业务代码运行时通过
`theme.C_X`（模块属性，实时）取色；`apply_theme` 会刷新这些模块级常量并切换
全局样式表。改主题只需在主循环里再调一次 `apply_theme`。
"""

from __future__ import annotations

from wbox import config as _app_config

# ---------------------------------------------------------------- 调色板
# 两套调色板键名完全一致；QSS 模板用 {KEY} 占位，CSS 自身花括号写成 {{ }}。
# 浅色 = 切回"最初最开始的白色"。

_DARK = {
    "C_BG": "#0C1017", "C_BG_ELEVATED": "#1D2330", "C_CARD": "#151A23",
    "C_CARD_HI": "#1D222A", "C_BORDER": "#262C36", "C_BORDER_DISABLED": "#1F242E",
    "C_FG": "#DCE0E5", "C_FG_MUTED": "#89929F",
    "C_PRIMARY": "#2BCAB5", "C_PRIMARY_HOVER": "#46D8C4", "C_PRIMARY_PRESSED": "#24A897",
    "C_PRIMARY_DIM": "#145D53", "C_PRIMARY_DISABLED_BG": "#1E4A44",
    "C_PRIMARY_DISABLED_TXT": "#6E8A85", "C_ON_PRIMARY": "#090D15",
    "C_SUCCESS": "#31A545", "C_WARNING": "#ED6E0C", "C_DANGER": "#EF4343", "C_INFO": "#2463EB",
    "C_SUCCESS_TXT": "#4CC96A", "C_WARNING_TXT": "#F5A44A",
    "C_DANGER_TXT": "#FF7A7A", "C_INFO_TXT": "#5B9BF5",
    "C_STATUSBAR_BG": "#080B11", "C_STEP_CHECKED_BG": "#17322D",
    "C_BADGE_OK_BG": "#1B3D24", "C_BADGE_OK_TXT": "#5FD97A",
    "C_BADGE_WARN_BG": "#4A2E0A", "C_BADGE_WARN_TXT": "#F5A44A",
    "C_BADGE_ERR_BG": "#4A1616", "C_BADGE_ERR_TXT": "#FF7A7A",
    "C_SCROLL_HANDLE": "#2A3442", "C_SCROLL_HANDLE_HOVER": "#3A4757",
    "C_PLACEHOLDER": "#5C6675",
}

_LIGHT = {
    "C_BG": "#FFFFFF", "C_BG_ELEVATED": "#F2F4F7", "C_CARD": "#FFFFFF",
    "C_CARD_HI": "#F2F4F7", "C_BORDER": "#D7DCE3", "C_BORDER_DISABLED": "#E2E6EC",
    "C_FG": "#1F2733", "C_FG_MUTED": "#5B6573",
    "C_PRIMARY": "#0FB5A6", "C_PRIMARY_HOVER": "#0CA093", "C_PRIMARY_PRESSED": "#0A8F82",
    "C_PRIMARY_DIM": "#D7F2EE", "C_PRIMARY_DISABLED_BG": "#BFE9E3",
    "C_PRIMARY_DISABLED_TXT": "#5C8A85", "C_ON_PRIMARY": "#05342F",
    "C_SUCCESS": "#1E8E3E", "C_WARNING": "#C2410C", "C_DANGER": "#D32F2F", "C_INFO": "#1D4ED8",
    "C_SUCCESS_TXT": "#15803D", "C_WARNING_TXT": "#B45309",
    "C_DANGER_TXT": "#D32F2F", "C_INFO_TXT": "#1D4ED8",
    "C_STATUSBAR_BG": "#EAEDF2", "C_STEP_CHECKED_BG": "#D7F2EE",
    "C_BADGE_OK_BG": "#DCFCE7", "C_BADGE_OK_TXT": "#15803D",
    "C_BADGE_WARN_BG": "#FEF3C7", "C_BADGE_WARN_TXT": "#B45309",
    "C_BADGE_ERR_BG": "#FEE2E2", "C_BADGE_ERR_TXT": "#D32F2F",
    "C_SCROLL_HANDLE": "#C7CDD6", "C_SCROLL_HANDLE_HOVER": "#AEB7C2",
    "C_PLACEHOLDER": "#8A93A0",
}

PALETTES = {"dark": _DARK, "light": _LIGHT}
THEME_NAMES = ("dark", "light")
THEME_LABELS = {"dark": "深色（IDE 风格）", "light": "浅色（经典白）"}

# 导入即初始化模块级 C_* 常量（默认按 dark 填值），保证 theme.C_X 随时可取；
# apply_theme 会按当前主题实时刷新这些全局量，业务代码统一用 theme.C_X 取实时色。
for _k, _v in _DARK.items():
    globals()[_k] = _v


# ---------------------------------------------------------------- QSS 模板
# 注意：CSS 自身的花括号必须写成 {{ / }}；颜色占位写成 {KEY}。
_QSS_TEMPLATE = """
* {{ font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif; font-size: 13px; }}
QMainWindow, QWidget {{ background: {C_BG}; color: {C_FG}; }}
QToolTip {{ background: {C_CARD}; color: {C_FG}; border: 1px solid {C_BORDER};
           border-radius: 6px; padding: 4px 8px; }}
QGroupBox {{ border: 1px solid {C_BORDER}; border-radius: 8px; margin-top: 10px;
            padding-top: 6px; background: {C_CARD}; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {C_FG_MUTED}; }}

/* 按钮：secondary 风（卡面底 + 细边框）；primary 风青绿底深字 */
QPushButton {{ background: {C_CARD}; border: 1px solid {C_BORDER}; border-radius: 8px;
              padding: 5px 14px; color: {C_FG}; }}
QPushButton:hover {{ background: {C_BG_ELEVATED}; border-color: #33405233; }}
QPushButton:pressed {{ background: {C_CARD_HI}; }}
QPushButton:disabled {{ color: {C_PLACEHOLDER}; background: {C_CARD}; border-color: {C_BORDER_DISABLED}; }}
QPushButton#primary {{ background: {C_PRIMARY}; border: 1px solid {C_PRIMARY}; color: {C_ON_PRIMARY};
                      font-weight: bold; border-radius: 8px; padding: 5px 16px; }}
QPushButton#primary:hover {{ background: {C_PRIMARY_HOVER}; border-color: {C_PRIMARY_HOVER}; }}
QPushButton#primary:pressed {{ background: {C_PRIMARY_PRESSED}; border-color: {C_PRIMARY_PRESSED}; }}
QPushButton#primary:disabled {{ background: {C_PRIMARY_DISABLED_BG}; border-color: {C_PRIMARY_DISABLED_BG};
                      color: {C_PRIMARY_DISABLED_TXT}; }}

/* 首页最近工程行的删除按钮（✕）：透明底、次要色，悬停变红 */
QPushButton#del {{ background: transparent; border: 1px solid {C_BORDER}; border-radius: 6px;
                  color: {C_FG_MUTED}; padding: 0; }}
QPushButton#del:hover {{ background: {C_BADGE_ERR_BG}; border-color: {C_BADGE_ERR_TXT};
                        color: {C_BADGE_ERR_TXT}; }}

/* 首页路径卡片（可点整卡） */
QFrame#card {{ background: {C_CARD}; border: 1px solid {C_BORDER}; border-radius: 10px; }}
QFrame#card:hover {{ background: {C_BG_ELEVATED}; border-color: {C_PRIMARY}; }}

/* 步骤导航 */
QPushButton#step {{ text-align: center; padding: 7px 14px; border: none; border-radius: 6px;
                   background: transparent; color: {C_FG_MUTED}; }}
QPushButton#step:hover {{ background: {C_BG_ELEVATED}; color: {C_FG}; }}
QPushButton#step:checked {{ background: {C_STEP_CHECKED_BG}; color: {C_PRIMARY}; font-weight: bold;
                           border-bottom: 2px solid {C_PRIMARY}; }}

/* 输入 */
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox {{ background: {C_CARD_HI};
    border: 1px solid {C_BORDER}; border-radius: 8px; padding: 4px 8px; color: {C_FG}; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {{ border: 1px solid {C_PRIMARY}; }}
QPlainTextEdit, QTextEdit {{ font-family: "Cascadia Mono", "Consolas", monospace; font-size: 12px; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{ background: {C_CARD}; border: 1px solid {C_BORDER};
    selection-background-color: {C_PRIMARY_DIM}; selection-color: {C_FG}; }}
QPlaceholderText {{ color: {C_PLACEHOLDER}; }}

/* 清单/表格 */
QTreeWidget, QTableWidget, QListWidget {{ background: {C_CARD}; border: 1px solid {C_BORDER};
    border-radius: 8px; alternate-background-color: {C_CARD_HI}; outline: none; }}
QTreeWidget::item, QListWidget::item {{ padding: 3px 2px; border-radius: 4px; }}
QTreeWidget::item:selected, QTableWidget::item:selected, QListWidget::item:selected {{
    background: {C_PRIMARY_DIM}; color: {C_FG}; }}
QTreeWidget::item:hover, QTableWidget::item:hover, QListWidget::item:hover {{ background: {C_BG_ELEVATED}; }}
QHeaderView::section {{ background: {C_BG_ELEVATED}; border: none;
    border-bottom: 1px solid {C_BORDER}; padding: 5px 6px; color: {C_FG_MUTED}; }}
QTableCornerButton::section {{ background: {C_BG_ELEVATED}; border: none; }}

/* Tab */
QTabWidget::pane {{ border: 1px solid {C_BORDER}; border-radius: 8px; background: {C_CARD}; }}
QTabBar::tab {{ background: transparent; border: none; padding: 6px 16px; margin-right: 2px;
               color: {C_FG_MUTED}; }}
QTabBar::tab:hover {{ color: {C_FG}; background: {C_BG_ELEVATED}; border-radius: 6px; }}
QTabBar::tab:selected {{ color: {C_PRIMARY}; font-weight: bold; border-bottom: 2px solid {C_PRIMARY}; }}

/* 文字层级 */
QLabel#h1 {{ font-size: 17px; font-weight: bold; color: {C_FG}; }}
QLabel#h2 {{ font-size: 14px; font-weight: bold; color: {C_FG}; }}
QLabel#muted {{ color: {C_FG_MUTED}; }}
QLabel#badge {{ background: {C_PRIMARY_DIM}; color: {C_PRIMARY}; border-radius: 10px;
               padding: 3px 12px; font-weight: bold; }}
QLabel#badge-ok {{ background: {C_BADGE_OK_BG}; color: {C_BADGE_OK_TXT}; border-radius: 10px; padding: 3px 12px; font-weight: bold; }}
QLabel#badge-warn {{ background: {C_BADGE_WARN_BG}; color: {C_BADGE_WARN_TXT}; border-radius: 10px; padding: 3px 12px; font-weight: bold; }}
QLabel#badge-err {{ background: {C_BADGE_ERR_BG}; color: {C_BADGE_ERR_TXT}; border-radius: 10px; padding: 3px 12px; font-weight: bold; }}

/* 状态栏 / 分隔 */
QStatusBar {{ background: {C_STATUSBAR_BG}; color: {C_FG_MUTED}; border-top: 1px solid {C_BORDER}; }}
QSplitter::handle {{ background: {C_BORDER}; }}
QSplitter::handle:horizontal {{ width: 2px; }}
QSplitter::handle:vertical {{ height: 2px; }}

/* 菜单 / 进度 / 勾选 */
QMenu {{ background: {C_CARD}; border: 1px solid {C_BORDER}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 5px 24px; border-radius: 4px; }}
QMenu::item:selected {{ background: {C_PRIMARY_DIM}; color: {C_FG}; }}
QMenu::separator {{ height: 1px; background: {C_BORDER}; margin: 4px 8px; }}
QProgressBar {{ background: {C_CARD_HI}; border: 1px solid {C_BORDER}; border-radius: 6px;
               text-align: center; color: {C_FG}; }}
QProgressBar::chunk {{ background: {C_PRIMARY}; border-radius: 4px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 14px; height: 14px; }}

/* 滚动条 */
QScrollBar:vertical {{ width: 10px; background: transparent; }}
QScrollBar::handle:vertical {{ background: {C_SCROLL_HANDLE}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {C_SCROLL_HANDLE_HOVER}; }}
QScrollBar:horizontal {{ height: 10px; background: transparent; }}
QScrollBar::handle:horizontal {{ background: {C_SCROLL_HANDLE}; border-radius: 5px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: {C_SCROLL_HANDLE_HOVER}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""


def build_qss(palette: dict) -> str:
    """按调色板填充模板，生成完整 QSS。"""
    return _QSS_TEMPLATE.format(**palette)


DARK_QSS = build_qss(_DARK)
LIGHT_QSS = build_qss(_LIGHT)

# 兼容旧名（老代码/文档若引用 LIGHT_QSS 不至于 ImportError）
QSS_BY_NAME = {"dark": DARK_QSS, "light": LIGHT_QSS}


def _read_config_theme() -> str:
    try:
        cfg = _app_config.load()
    except Exception:  # noqa: BLE001  读不到就用默认
        return "dark"
    ui = cfg.get("ui", {})
    # 旧版本默认是 light，但那时没有主题切换；为保持用户既有的深色外观，
    # 未显式选过主题（theme_chosen 不为真）时一律按 dark 处理。
    if not ui.get("theme_chosen"):
        return "dark"
    return str(ui.get("theme", "dark"))


def apply_theme(app, theme_name: str | None = None) -> str:
    """应用主题到 app。返回实际应用的主题名。

    theme_name 为 None 时读 config.ui.theme（默认 dark）。
    同时刷新本模块 C_* 模块级常量（兼容仍以 from import 引入的极少数场景；
    主路径业务代码请用 theme.C_X 取实时色）。
    """
    name = theme_name or _read_config_theme()
    if name not in PALETTES:
        name = "dark"
    palette = PALETTES[name]
    g = globals()
    for key, val in palette.items():
        if key in g:
            g[key] = val
    app.setStyleSheet(QSS_BY_NAME[name])
    return name
