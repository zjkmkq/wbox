"""wbox.gui.pages.knowledge —— 迁移知识库：按形态浏览迁移打法。

存在理由：形态模板（src/wbox/shapes/*.json）里沉淀了每类 APK 的完整打法
（步骤 / 资源策略 / 桥接 / 坑 / 验收清单），但 JSON 不是给人读的。本页把它
渲染成可检索、可通读的中文文档：左边挑形态，右边看全文。

数据源只有 wbox.shape，不复制一份文档（避免两边漂移）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from wbox import shape as shape_mod
from wbox.gui.uikit import harden_label, harden_window, plain_text, wrap_label


def shape_markdown(shape: dict) -> str:
    """把形态模板渲染成 Markdown（QTextBrowser.setMarkdown 直接吃）。"""
    lines: list[str] = []
    name = shape.get("name") or shape.get("shape_id") or "未命名形态"
    lines.append(f"# {name}")
    lines.append("")
    meta = []
    if shape.get("shape_id"):
        meta.append(f"形态 ID：`{shape['shape_id']}`")
    if shape.get("effort"):
        meta.append(f"预计工作量：{shape['effort']}")
    if shape.get("tags"):
        meta.append("标签：" + "、".join(str(t) for t in shape["tags"]))
    if meta:
        lines.append("　·　".join(meta))
        lines.append("")
    if shape.get("summary"):
        lines.append(str(shape["summary"]))
        lines.append("")

    migrate = shape.get("migrate") or {}
    if migrate.get("approach"):
        lines.append(f"## 迁移路线：{migrate['approach']}")
        if migrate.get("why"):
            lines.append("")
            lines.append(str(migrate["why"]))
        lines.append("")
    steps = migrate.get("steps") or []
    if steps:
        lines.append("## 迁移步骤")
        lines.append("")
        for i, s in enumerate(steps, 1):
            lines.append(f"{i}. {s}")
        lines.append("")
    res = migrate.get("resource_strategy") or {}
    if res:
        lines.append("## 资源策略")
        lines.append("")
        lines.append(f"- 模式：`{res.get('mode', '—')}`")
        lines.append(f"- 说明：{res.get('note', '—')}")
        lines.append("")
    bridges = migrate.get("bridge") or []
    if bridges:
        lines.append("## 需要补的桥")
        lines.append("")
        for b in bridges:
            lines.append(f"- **{b.get('need', '')}**：{b.get('reason', '')}")
            lines.append(f"  - 做法：{b.get('how', '')}")
        lines.append("")
    prof = migrate.get("renderer_profile") or {}
    if prof:
        lines.append("## 渲染器画像")
        lines.append("")
        for key, label in (("rule", "规则"), ("why", "原因"), ("fallback", "回落"), ("probe", "探针")):
            if prof.get(key):
                lines.append(f"- {label}：{prof[key]}")
        lines.append("")
    pitfalls = migrate.get("pitfalls") or []
    if pitfalls:
        lines.append("## 已知坑")
        lines.append("")
        for p in pitfalls:
            lines.append(f"- **现象**：{p.get('symptom', '')}")
            lines.append(f"  - 原因：{p.get('cause', '')}")
            lines.append(f"  - 解法：{p.get('fix', '')}")
        lines.append("")
    verify = migrate.get("verify") or []
    if verify:
        lines.append("## 验收清单")
        lines.append("")
        for v in verify:
            lines.append(f"- [ ] {v}")
        lines.append("")
    cases = shape.get("cases") or []
    if cases:
        lines.append("## 已验证案例")
        lines.append("")
        for c in cases:
            bits = [c.get("name", "")]
            if c.get("bundle"):
                bits.append(f"`{c['bundle']}`")
            if c.get("engine"):
                bits.append(c["engine"])
            if c.get("hap_bytes"):
                bits.append(f"HAP {int(c['hap_bytes']) / 1048576:.1f} MB")
            lines.append("- " + "　".join(b for b in bits if b))
            if c.get("note"):
                lines.append(f"  - {c['note']}")
        lines.append("")
    detect = shape.get("detect") or {}
    if detect:
        lines.append("## 识别规则（诊断仪据此打分）")
        lines.append("")
        for kind, label in (("any", "存在性"), ("contains", "内容特征"), ("exclude", "排除项")):
            rules = detect.get(kind) or []
            if not rules:
                continue
            lines.append(f"- {label}：")
            for r in rules:
                extra = f"　命中串 /{r['pattern']}/" if r.get("pattern") else ""
                lines.append(f"  - `{r.get('path_glob', '')}`{extra}")
        lines.append("")
    return "\n".join(lines)


class KnowledgePage(QWidget):
    """知识库页面：左列表（可搜索）+ 右全文（Markdown 渲染）。"""

    back = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._shapes: list[dict] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)

        head = QHBoxLayout()
        btn_back = QPushButton("← 首页")
        btn_back.clicked.connect(lambda: self.back.emit())
        head.addWidget(btn_back)
        title = QLabel("迁移知识库")
        title.setObjectName("h1")
        head.addWidget(title)
        head.addStretch(1)
        lay.addLayout(head)

        lay.addWidget(self._build_meta_box())

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索形态：名称 / 标签 / 正文关键词…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.list = QListWidget()
        # 形态名可能很长（"Cordova/Capacitor 壳 + H5 游戏（…）"），必须换行显示，
        # 否则列表里会被硬切掉半截（QListWidget 默认不换行、也不加省略号）
        self.list.setWordWrap(True)
        self.list.currentItemChanged.connect(self._show_current)
        split.addWidget(self.list)
        self.doc = QTextBrowser()
        self.doc.setOpenExternalLinks(True)
        self.doc.setLineWrapMode(QTextBrowser.LineWrapMode.WidgetWidth)
        split.addWidget(self.doc)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 5)
        split.setCollapsible(0, False)
        split.setCollapsible(1, False)
        lay.addWidget(split, stretch=1)

        self.count_label = QLabel("")
        self.count_label.setObjectName("muted")
        lay.addWidget(self.count_label)

        harden_window(self)
        self.reload()

    # ------------------------------------------------------------ 三条铁律

    def _build_meta_box(self) -> QWidget:
        """页面顶部的「三条铁律」区（数据源：`shapes/_meta.json` 的 load_meta()）。

        为什么放在最上面而不是某个二级页：这三条是全部模板的总纲（先判形态 /
        不干预渲染器 / 每步自证），用户明确要求"位置要显眼"。读不到就返回空容器，
        绝不因为缺文件让整页打不开。
        """
        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)

        meta = shape_mod.load_meta(force=True) or {}
        rules = shape_mod.meta_rules()
        if not meta and not rules:
            note = wrap_label("（未读到形态元规则 _meta.json：知识库照常可用，只是缺了总纲）",
                              object_name="muted")
            col.addWidget(note)
            return box

        head_row = QHBoxLayout()
        head = QLabel("三条铁律（形态模板的总纲）")
        head.setObjectName("h2")
        head_row.addWidget(head)
        self._meta_head = head
        head_row.addSpacing(10)
        self.btn_meta = QPushButton("收起")
        self.btn_meta.setToolTip("收起/展开三条铁律：关心形态细节时可让它让出空间")
        self.btn_meta.clicked.connect(lambda: self._toggle_meta())
        head_row.addWidget(self.btn_meta)
        head_row.addStretch(1)
        col.addLayout(head_row)

        intro = str(meta.get("intro") or "").strip()
        if intro:
            col.addWidget(wrap_label(intro))

        for rule in rules:
            card = QFrame()
            card.setObjectName("card")
            card_lay = QVBoxLayout(card)
            card_lay.setContentsMargins(14, 10, 14, 10)
            card_lay.setSpacing(4)

            row = QHBoxLayout()
            badge = QLabel(str(rule.get("id") or "·"))
            badge.setObjectName("badge")   # 短徽标：不走自动换行，保留单行
            row.addWidget(badge)
            title = QLabel(str(rule.get("title") or ""))
            title.setObjectName("h2")
            row.addWidget(title)
            row.addStretch(1)
            card_lay.addLayout(row)

            body = str(rule.get("body") or "").strip()
            if body:
                lbl_body = QLabel(body)
                harden_label(lbl_body)          # 长段落：先加固再入布局，避免被压竖排
                card_lay.addWidget(lbl_body)

            enforced = str(rule.get("enforced_by") or "").strip()
            if enforced:
                lbl_enforced = QLabel(f"由谁兜底：{enforced}")
                lbl_enforced.setObjectName("muted")
                harden_label(lbl_enforced)
                card_lay.addWidget(lbl_enforced)
            col.addWidget(card)

        foot_bits = [x for x in (
            f"版本 v{meta['version']}" if meta.get("version") else "",
            f"更新于 {meta['updated']}" if meta.get("updated") else "",
        ) if x]
        if foot_bits:
            lbl_foot = QLabel("　·　".join(foot_bits))
            lbl_foot.setObjectName("muted")
            col.addWidget(lbl_foot)

        # 尾部弹簧：把"多余高度"全给弹簧，标签才不会被拉成比正文高两倍的空白块
        # （实测没有这行时，标题 QLabel 会从 28px 被撑到 162px，卡片直接被挤出可视区）
        col.addStretch(1)

        # 铁律正文很长，限高 + 滚动：不能把下面的形态列表挤出屏幕。
        # 高度上限 320 是量出来的（标题+引言+R1 = 约 300px）；超出部分用滚动看，
        # 但顶部一定要露出至少完整的一条，否则用户会误以为被截断了。
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setMaximumHeight(320)
        area.setWidget(box)
        self._meta_area = area
        return area

    def _toggle_meta(self) -> None:
        """收起/展开三条铁律（收起后只留一行标题，给形态列表腾地方）。"""
        area = getattr(self, "_meta_area", None)
        if area is None:
            return
        collapsed = area.maximumHeight() > 100
        area.setMaximumHeight(40 if collapsed else 320)
        self.btn_meta.setText("展开" if collapsed else "收起")
        self.btn_meta.setToolTip("三条铁律：先判形态 / 不干预渲染器 / 每步自证")

    def showEvent(self, event) -> None:  # noqa: N802  Qt 命名
        """首次显示时按"已加载 QSS 的字体"量一次最小宽度。

        起因：QLabel 开 wordWrap 后 sizeHint 的宽是按启发式估的（偏窄），
        同一行又有弹簧吃满剩余空间，于是"三条铁律（形态模板的总纲）"被压成两行、
        「收起」按钮被压成竖排两个字。构造时机还没加载 QSS，字宽算不准；
        显示时字体已定，这时候量才准。
        """
        super().showEvent(event)
        head = getattr(self, "_meta_head", None)
        if head is not None:
            width = head.fontMetrics().horizontalAdvance(head.text()) + 12
            if head.minimumWidth() < width:
                head.setMinimumWidth(width)
        btn = getattr(self, "btn_meta", None)
        if btn is not None:
            need = btn.fontMetrics().horizontalAdvance("展开") + 28
            if btn.minimumWidth() < need:
                btn.setMinimumWidth(need)

    # ------------------------------------------------------------ 数据

    def reload(self) -> None:
        self._shapes = shape_mod.load_shapes(force=True)
        self._fill(self._shapes)

    def _fill(self, shapes: list[dict]) -> None:
        self.list.clear()
        for s in shapes:
            item = QListWidgetItem(str(s.get("name") or s.get("shape_id") or ""))
            tags = "、".join(str(t) for t in (s.get("tags") or []))
            tip = "\n".join(x for x in (
                str(s.get("name") or ""), f"形态 ID：{s.get('shape_id', '')}",
                f"工作量：{s.get('effort', '—')}", f"标签：{tags}",
                str(s.get("summary") or "")) if x)
            item.setToolTip(plain_text(tip))
            item.setData(Qt.ItemDataRole.UserRole, str(s.get("shape_id") or ""))
            self.list.addItem(item)
        self.count_label.setText(f"共 {len(shapes)} 个形态模板"
                                 + ("" if shapes else "（模板目录为空：src/wbox/shapes/）"))
        if shapes:
            self.list.setCurrentRow(0)

    def _filter(self, text: str) -> None:
        keyword = (text or "").strip().lower()
        if not keyword:
            self._fill(self._shapes)
            return
        hits = []
        for s in self._shapes:
            hay = " ".join([
                str(s.get("name") or ""), str(s.get("shape_id") or ""),
                " ".join(str(t) for t in (s.get("tags") or [])),
                shape_markdown(s),
            ]).lower()
            if keyword in hay:
                hits.append(s)
        self._fill(hits)

    def _show_current(self, current: QListWidgetItem | None, _prev=None) -> None:
        if current is None:
            return
        sid = current.data(Qt.ItemDataRole.UserRole)
        shape = next((s for s in self._shapes if s.get("shape_id") == sid), None)
        if shape is None:
            self.doc.setMarkdown("（模板已失效）")
            return
        self.doc.setMarkdown(shape_markdown(shape))

    def show_shape(self, shape_id: str) -> None:
        """外部（如诊断仪）直接定位到某个形态。"""
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.ItemDataRole.UserRole) == shape_id:
                self.list.setCurrentRow(i)
                return
