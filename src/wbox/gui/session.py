"""wbox.gui.session —— 工程会话：spec 的唯一 GUI 侧出入口。

工程目录布局（写死）：
    <project>/
      spec.json   契约（只经 wbox.spec 读写）
      work/       apktool 解包输出（smali/resources/assets）
      draft/      「填上」步生成的鸿蒙工程树
      exports/    任务包等导出物
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from wbox.spec import SPEC_VERSION, SpecError, load, save


class ProjectSession(QObject):
    """持有打开的 spec；任何修改必须经 save() 落盘后广播 changed。"""

    changed = Signal(str)        # 变更说明（供状态栏/刷新用）
    loaded = Signal()

    def __init__(self, project_dir: str | Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.project_dir = Path(project_dir).resolve()
        self.spec_path = self.project_dir / "spec.json"
        self.spec: dict = {}
        self._dirty = False

    @classmethod
    def create_new(cls, project_dir: str | Path, apk_path: str | Path,
                   name: str = "", parent: QObject | None = None) -> "ProjectSession":
        """新建工程：落一份最小合法 spec（空清单），等「拆」步填充。"""
        s = cls(project_dir, parent)
        s.ensure_dirs()
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        s.spec = {
            "spec_version": SPEC_VERSION,
            "project": {
                "name": name or Path(apk_path).stem,
                "source": str(apk_path),
                "target": "harmonyos-next",
                "created_at": now,
                "updated_at": now,
            },
            "resources": [], "modules": [], "behaviors": [],
            "decisions": [], "build_log": [], "seams": [],
        }
        s.save("新建工程")
        return s

    # ------------------------------------------------------------ 目录

    @property
    def work_dir(self) -> Path:
        return self.project_dir / "work"

    @property
    def draft_dir(self) -> Path:
        return self.project_dir / "draft"

    @property
    def exports_dir(self) -> Path:
        return self.project_dir / "exports"

    def ensure_dirs(self) -> None:
        for d in (self.work_dir, self.draft_dir, self.exports_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ 读写

    def load(self) -> None:
        if not self.spec_path.is_file():
            raise SpecError(f"工程目录下没有 spec.json：{self.project_dir}")
        self.spec = load(self.spec_path)
        self._dirty = False
        self.ensure_dirs()
        self.loaded.emit()

    def save(self, note: str = "") -> None:
        if not self.spec:
            raise SpecError("没有可保存的 spec（工程未打开）")
        self.ensure_dirs()
        save(self.spec, self.spec_path)
        self._dirty = False
        self.changed.emit(note or "已保存")

    def update(self, note: str) -> None:
        """标记内存中的 spec 已改（未落盘）。"""
        self._dirty = True
        self.changed.emit(note + "（未保存）")

    @property
    def dirty(self) -> bool:
        return self._dirty

    # ------------------------------------------------------------ 便捷读取

    @property
    def project_name(self) -> str:
        return str(self.spec.get("project", {}).get("name") or self.project_dir.name)

    @property
    def resources(self) -> list[dict]:
        return self.spec.get("resources", [])

    @property
    def modules(self) -> list[dict]:
        return self.spec.get("modules", [])

    @property
    def behaviors(self) -> list[dict]:
        return self.spec.get("behaviors", [])

    @property
    def decisions(self) -> list[dict]:
        return self.spec.get("decisions", [])

    @property
    def seams(self) -> list[dict]:
        return self.spec.get("seams", [])

    @property
    def build_log(self) -> list[dict]:
        return self.spec.get("build_log", [])

    def next_id(self, section: str, prefix: str, width: int = 3) -> str:
        """生成段内下一个自增 id（如 seam_107 / dec_008）。"""
        items = self.spec.get(section, [])
        max_n = 0
        for it in items:
            iid = str(it.get("id", ""))
            if iid.startswith(prefix):
                try:
                    max_n = max(max_n, int(iid[len(prefix):]))
                except ValueError:
                    pass
        return f"{prefix}{max_n + 1:0{width}d}"
