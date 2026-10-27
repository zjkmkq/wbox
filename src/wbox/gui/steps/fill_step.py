"""wbox.gui.steps.fill_step —— ④ 填上：按提案生成 ArkTS 草案，落 draft/ 目录。

三个通道（写死，产物统一走 wbox.draft 落盘）：
  A 任务包导出：build_taskpack → exports/ 目录，整个粘给任意 AI（无需 key）
  B API 直连：  render_prompt + methodology 作 system，流式生成，自动落盘
  C 粘贴导入：  把别处 AI 的输出粘进来，解析 FILE 段落盘
落盘成功写 spec.build_log（action=draft_generated），回「补缝」步编译验证。
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
)

from wbox import aiclient
from wbox import config as app_config
from wbox import draft as draft_mod
from wbox import taskpack
from wbox.gui import theme
from wbox.gui.session import ProjectSession
from wbox.gui.steps import StepPage, register

_SMALI_MAX_FILES = 10
_SMALI_MAX_BYTES = 8000

_DROP_EXTS = {".md", ".txt", ".ets", ".json", ".markdown"}


class _DropPasteEdit(QPlainTextEdit):
    """粘贴框增强：支持把文件拖进来——读文件内容填入，而非插入路径。

    用户实测把 ai_output.md / 任务包拖进来只写零个文件：普通编辑框
    拖入只落一个路径字符串，parse_draft 自然找不到 FILE 块。拖文件
    → 读全文进框，纯文本拖拽仍走默认插入。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        md = event.mimeData()
        if md.hasUrls() or md.hasText():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        md = event.mimeData()
        if md.hasUrls():
            for url in md.urls():
                p = url.toLocalFile()
                if not p:
                    continue
                fp = Path(p)
                if fp.is_file() and fp.suffix.lower() in _DROP_EXTS:
                    try:
                        self.setPlainText(
                            fp.read_text(encoding="utf-8", errors="replace")
                        )
                    except OSError:
                        continue
                    event.acceptProposedAction()
                    return
        super().dropEvent(event)


class _GenWorker(QThread):
    """AI 直连生成 / 测试连接。流式增量经 delta 抛出。"""

    delta = Signal(str)
    done = Signal(bool, str)          # ok, text_or_error

    def __init__(self, client: aiclient.AIClient, prompt: str, system: str, test: bool) -> None:
        super().__init__()
        self.client = client
        self.prompt = prompt
        self.system = system
        self.test = test

    def run(self) -> None:
        try:
            if self.test:
                r = self.client.chat("回复两个字：就绪", system="你是连通性测试探针。")
            else:
                chunks: list[str] = []

                def _on_delta(text: str) -> None:
                    chunks.append(text)
                    self.delta.emit(text)

                r = self.client.chat_stream(self.prompt, system=self.system,
                                            on_delta=_on_delta)
            if r.ok:
                self.done.emit(True, r.text)
            else:
                self.done.emit(False, r.error or "生成失败")
        except Exception as e:  # noqa: BLE001  网络异常不许崩线程
            self.done.emit(False, f"生成异常：{e}")


@register
class FillStep(StepPage):
    step_id = "fill"
    title = "④ 填上"
    subtitle = "按提案与决策生成 ArkTS 草案：A 任务包导出（粘给任意 AI）/ B 应用内 API 直连 / C 粘贴导入；产物统一落 draft/"

    # ------------------------------------------------------------ 构建

    def _build_body(self) -> None:
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_channel_a(), "A · 任务包导出")
        self.tabs.addTab(self._build_channel_b(), "B · API 直连")
        self.tabs.addTab(self._build_channel_c(), "C · 粘贴导入")
        self.body.addWidget(self.tabs, stretch=1)
        self._worker: _GenWorker | None = None
        self._last_output = ""

    def _build_channel_a(self):
        w = QVBoxLayout()
        info = QLabel(
            "导出任务包（prompt.md + methodology.md + spec.json + 关键 smali）到 exports/ 目录。"
            "把整个目录粘给任意大模型（网页版 ChatGPT/Claude/DeepSeek 均可），"
            "拿回的输出用右侧「C · 粘贴导入」落盘。无需 API key。")
        info.setWordWrap(True)
        w.addWidget(info)
        row = QHBoxLayout()
        self.btn_export = QPushButton("导出任务包")
        self.btn_export.setObjectName("primary")
        self.btn_export.clicked.connect(self._export_taskpack)
        row.addWidget(self.btn_export)
        self.btn_open_exports = QPushButton("打开 exports 目录")
        self.btn_open_exports.clicked.connect(self._open_exports)
        row.addWidget(self.btn_open_exports)
        row.addStretch(1)
        w.addLayout(row)
        self.export_status = QLabel("")
        self.export_status.setWordWrap(True)
        w.addWidget(self.export_status)
        w.addStretch(1)
        holder = QVBoxLayout()
        holder.addLayout(w)
        from PySide6.QtWidgets import QWidget
        c = QWidget()
        c.setLayout(holder)
        return c

    def _build_channel_b(self):
        from PySide6.QtWidgets import QWidget

        w = QVBoxLayout()
        cfg = app_config.load().get("ai", {})
        row = QHBoxLayout()
        row.addWidget(QLabel("base_url："))
        self.ed_base = QLineEdit(cfg.get("base_url", ""))
        self.ed_base.setPlaceholderText("https://api.deepseek.com/v1")
        row.addWidget(self.ed_base, stretch=2)
        row.addWidget(QLabel("model："))
        self.ed_model = QLineEdit(cfg.get("model", ""))
        self.ed_model.setPlaceholderText("deepseek-chat")
        row.addWidget(self.ed_model, stretch=1)
        w.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("api_key："))
        self.ed_key = QLineEdit(cfg.get("api_key", ""))
        self.ed_key.setEchoMode(QLineEdit.EchoMode.Password)
        row2.addWidget(self.ed_key, stretch=2)
        self.btn_save_cfg = QPushButton("保存配置")
        self.btn_save_cfg.clicked.connect(self._save_ai_cfg)
        row2.addWidget(self.btn_save_cfg)
        self.btn_test = QPushButton("测试连接")
        self.btn_test.clicked.connect(lambda: self._run_ai(test=True))
        row2.addWidget(self.btn_test)
        self.btn_gen = QPushButton("开始生成")
        self.btn_gen.setObjectName("primary")
        self.btn_gen.clicked.connect(lambda: self._run_ai(test=False))
        row2.addWidget(self.btn_gen)
        w.addLayout(row2)

        self.gen_console = QPlainTextEdit()
        self.gen_console.setReadOnly(True)
        self.gen_console.setMaximumBlockCount(8000)
        self.gen_console.setStyleSheet("font-family: Consolas, 'Courier New', monospace;")
        w.addWidget(self.gen_console, stretch=1)
        self.gen_status = QLabel("")
        self.gen_status.setWordWrap(True)
        w.addWidget(self.gen_status)
        row3 = QHBoxLayout()
        self.btn_open_draft_b = QPushButton("打开 draft 目录")
        self.btn_open_draft_b.clicked.connect(self._open_draft)
        row3.addWidget(self.btn_open_draft_b)
        self.draft_count_b = QLabel("")
        self.draft_count_b.setObjectName("muted")
        row3.addWidget(self.draft_count_b, stretch=1)
        w.addLayout(row3)
        c = QWidget()
        c.setLayout(w)
        return c

    def _build_channel_c(self):
        from PySide6.QtWidgets import QWidget

        w = QVBoxLayout()
        w.addWidget(QLabel(
            "把 AI 的输出粘贴到下面——必须是含 ```ets 代码块、块内首行\n"
            "  // FILE: 路径 的代码文本（任务包 prompt.md/smali 粘进来无效，\n"
            "那是给 AI 的输入，不是 AI 的产出）。"))
        self.paste_box = _DropPasteEdit()
        self.paste_box.setPlaceholderText(
            "示例：\n```ets\n// FILE: logic/W0G.ets\n<文件完整内容>\n```\n\n"
            "拿不到这种输出？把 A 通道导出的任务包粘给任意 AI\n"
            "（本工作台聊天窗即可），让它按 methodology.md 第 4 节生成。")
        w.addWidget(self.paste_box, stretch=1)
        row = QHBoxLayout()
        self.btn_apply_paste = QPushButton("解析并落盘到 draft/")
        self.btn_apply_paste.setObjectName("primary")
        self.btn_apply_paste.clicked.connect(self._apply_paste)
        row.addWidget(self.btn_apply_paste)
        self.paste_status = QLabel("")
        self.paste_status.setWordWrap(True)
        row.addWidget(self.paste_status)
        row.addStretch(1)
        w.addLayout(row)
        row3 = QHBoxLayout()
        self.btn_open_draft_c = QPushButton("打开 draft 目录")
        self.btn_open_draft_c.clicked.connect(self._open_draft)
        row3.addWidget(self.btn_open_draft_c)
        self.draft_count_c = QLabel("")
        self.draft_count_c.setObjectName("muted")
        row3.addWidget(self.draft_count_c, stretch=1)
        w.addLayout(row3)
        c = QWidget()
        c.setLayout(w)
        return c

    # ------------------------------------------------------------ 通道 A

    def _export_taskpack(self) -> None:
        if "proposal" not in self.session.spec:
            self.export_status.setText("请先在「② 画拼图」生成提案，再导出任务包")
            return
        out = self.session.exports_dir / "taskpack"
        try:
            taskpack.build_taskpack(self.session.spec_path, out)
        except Exception as e:  # noqa: BLE001
            self.export_status.setText(f"导出失败：{e}")
            return
        files = sorted(p.name for p in out.rglob("*") if p.is_file())
        self._set_badge(self.export_status, "ok",
            f"✓ 任务包已生成（{len(files)} 个文件）：{out}\n"
            f"含：{'、'.join(files[:8])}{' …' if len(files) > 8 else ''}")
        self.export_status.setToolTip(
            "完整文件清单：\n" + "\n".join("  • " + f for f in files)
            + "\n\n把整个目录粘给任意 AI，拿回的输出用「C · 粘贴导入」落盘。")

    def _open_exports(self) -> None:
        d = self.session.exports_dir
        d.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(str(d))  # noqa: S606  Windows 资源管理器打开

    # ------------------------------------------------------------ 通道 B

    def _save_ai_cfg(self) -> None:
        cfg = app_config.load()
        cfg["ai"] = {
            "base_url": self.ed_base.text().strip(),
            "api_key": self.ed_key.text().strip(),
            "model": self.ed_model.text().strip(),
        }
        app_config.save(cfg)
        self.gen_status.setText("AI 配置已保存（仅存本机）")

    def _run_ai(self, test: bool) -> None:
        cfg = app_config.load().get("ai", {})
        base = self.ed_base.text().strip()
        key = self.ed_key.text().strip()
        model = self.ed_model.text().strip()
        client = aiclient.AIClient(base, key, model)
        if not client.configured:
            self.gen_status.setText("请先填全 base_url / api_key / model 并保存")
            return
        if test:
            self.btn_test.setEnabled(False)
            self.gen_status.setText("测试连接中…")
            worker = _GenWorker(client, "", "", test=True)
        else:
            if "proposal" not in self.session.spec:
                self.gen_status.setText("请先在「② 画拼图」生成提案")
                return
            # 复用任务包渲染，保证与通道 A 内容一致；smali 正文附在 prompt 后
            pack = self.session.exports_dir / "taskpack"
            try:
                taskpack.build_taskpack(self.session.spec_path, pack)
            except Exception as e:  # noqa: BLE001
                self.gen_status.setText(f"渲染指令失败：{e}")
                return
            prompt = (pack / "prompt.md").read_text(encoding="utf-8")
            smali_dir = pack / "smali"
            if smali_dir.is_dir():
                files = sorted(smali_dir.glob("*.smali"))[:_SMALI_MAX_FILES]
                if files:
                    prompt += "\n\n## 附：关键 smali 源码\n"
                    for f in files:
                        body = f.read_text(encoding="utf-8", errors="replace")[:_SMALI_MAX_BYTES]
                        prompt += f"\n### {f.name}\n```smali\n{body}\n```\n"
            self.btn_gen.setEnabled(False)
            self.gen_status.setText("生成中（流式输出，大工程可能数分钟）…")
            self.gen_console.clear()
            self._last_output = ""
            worker = _GenWorker(client, prompt,
                                (pack / "methodology.md").read_text(encoding="utf-8"),
                                test=False)
        worker.delta.connect(self._on_delta)
        worker.done.connect(lambda ok, text: self._on_gen_done(ok, text, test))
        self._worker = worker
        worker.start()

    def _on_delta(self, text: str) -> None:
        self.gen_console.insertPlainText(text)
        self._last_output += text

    def _on_gen_done(self, ok: bool, text: str, test: bool) -> None:
        self.btn_test.setEnabled(True)
        self.btn_gen.setEnabled(True)
        if test:
            self.gen_status.setText(("连接成功：" + text[:60]) if ok else f"连接失败：{text}")
            return
        if not ok:
            self._set_badge(self.gen_status, "err", f"✗ 生成失败：{text}")
            return
        # 自动落盘 draft/（解析器只接受相对路径，安全）
        result = draft_mod.apply_draft(text, self.session.draft_dir)
        summary = draft_mod.draft_summary(result)
        self._last_output = text
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        module_id = "mod_001"
        mods = self.session.spec.get("modules", [])
        if mods and isinstance(mods[0], dict) and mods[0].get("id"):
            module_id = str(mods[0]["id"])
        self.session.spec.setdefault("build_log", []).append({
            "id": self.session.next_id("build_log", "log_"),
            "module_id": module_id,
            "action": "draft_generated",
            "summary": f"API 直连生成 ArkTS 草案：{summary}",
            "diff_ref": str(self.session.draft_dir),
            "at": now,
        })
        self.session.save("AI 生成草案")
        tip = self._files_tip(result.written)
        if result.notes:
            tip += "\n\n附加节首行：" + result.notes.splitlines()[0][:120]
        self._set_badge(self.gen_status, "ok",
            f"✓ 已落盘 draft/：{summary}\n下一步到「⑤ 装配」生成可编译工程，再到「⑥ 补缝」编译验证。")
        self.gen_status.setToolTip(tip)

    # ------------------------------------------------------------ 通道 C

    def _apply_paste(self) -> None:
        text = self.paste_box.toPlainText()
        if not text.strip():
            self._set_badge(self.paste_status, "warn", "请先粘贴 AI 输出内容（含 // FILE: 的代码块）。")
            return
        # 输入类型识别：任务包/路径误粘进来时给出明确指引，而不是干巴巴"写入 0 个"
        if "// FILE:" not in text:
            looks_taskpack = (
                "smali/" in text or "spec.json" in text
                or "任务" in text[:200] or "提案" in text[:200]
                or (len(text) < 400 and ("/" in text or "\\" in text)
                    and not text.lstrip().startswith("```"))
            )
            if looks_taskpack:
                self._set_badge(self.paste_status, "warn",
                    "⚠ 粘进来的像是任务包/路径，不是 AI 的产出。\n"
                    "任务包是给 AI 的输入——请把它粘给任意 AI（如本聊天窗），\n"
                    "拿回含 ```ets 代码块 + // FILE: 路径 的输出后再粘到这里。")
            else:
                self._set_badge(self.paste_status, "warn",
                    "没找到任何 // FILE: 段落。请确认 AI 按 methodology.md "
                    "第 4 节的 FILE 格式输出（```ets 块内首行 // FILE: 路径）。")
            return
        result = draft_mod.apply_draft(text, self.session.draft_dir)
        summary = draft_mod.draft_summary(result)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        module_id = "mod_001"
        mods = self.session.spec.get("modules", [])
        if mods and isinstance(mods[0], dict) and mods[0].get("id"):
            module_id = str(mods[0]["id"])
        self.session.spec.setdefault("build_log", []).append({
            "id": self.session.next_id("build_log", "log_"),
            "module_id": module_id,
            "action": "draft_generated",
            "summary": f"粘贴导入 ArkTS 草案：{summary}",
            "diff_ref": str(self.session.draft_dir),
            "at": now,
        })
        self.session.save("粘贴导入草案")
        self._set_badge(self.paste_status, "ok", f"✓ 已落盘 draft/：{summary}")
        self.paste_status.setToolTip(self._files_tip(result.written))

    # ------------------------------------------------------------ 反馈辅助

    def _set_badge(self, label: QLabel, kind: str, text: str) -> None:
        """把 QLabel 渲染成醒目徽标（ok/warn/err），运行时直接设样式，切主题也跟随。"""
        colors = {
            "ok": (theme.C_BADGE_OK_BG, theme.C_BADGE_OK_TXT),
            "warn": (theme.C_BADGE_WARN_BG, theme.C_BADGE_WARN_TXT),
            "err": (theme.C_BADGE_ERR_BG, theme.C_BADGE_ERR_TXT),
        }
        bg, fg = colors.get(kind, (theme.C_CARD, theme.C_FG))
        label.setStyleSheet(
            f"background: {bg}; color: {fg}; border-radius: 8px; "
            f"padding: 6px 10px; font-weight: bold;"
        )
        label.setText(text)
        label.setWordWrap(True)

    def _files_tip(self, written: list[str]) -> str:
        if not written:
            return "（无文件写入）"
        return "写入文件：\n" + "\n".join("  • " + w for w in written)

    def _draft_count_text(self) -> str:
        d = self.session.draft_dir
        if not d.is_dir():
            return "当前 draft/ 暂无文件"
        n = sum(1 for _ in d.rglob("*") if _.is_file())
        return f"当前 draft/ 共 {n} 个文件（落盘即'填上'生效，可点'打开 draft 目录'核对）"

    def _open_draft(self) -> None:
        d = self.session.draft_dir
        d.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(str(d))  # noqa: S606  Windows 资源管理器打开

    # ------------------------------------------------------------ 刷新

    def refresh(self) -> None:
        has = "proposal" in self.session.spec
        if not has:
            self.export_status.setText("尚未生成提案（② 画拼图）——任务包与直连都需要提案")
            self.gen_status.setText("尚未生成提案（② 画拼图）")
        # 各通道底部的 draft 计数（让用户随时核对"填上"落盘情况）
        for attr in ("draft_count_b", "draft_count_c"):
            lbl = getattr(self, attr, None)
            if lbl is not None:
                lbl.setText(self._draft_count_text())

    def on_enter(self) -> None:
        self.refresh()
