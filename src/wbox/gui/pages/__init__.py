"""wbox.gui.pages —— 首页五条路径里除工作区外的三个独立页面。

- doctor.py       形态诊断仪（丢 APK → 出形态/能不能迁/几步/坑）
- knowledge.py    迁移知识库（形态模板 + 教程浏览）
- troubleshoot.py 排障台（所有工程的缝清单 + 失败案例 + 日志检索）

共同约定：每个页面都发 back 信号请求回首页，不自己管窗口栈。
"""

from wbox.gui.pages.doctor import DoctorPage  # noqa: F401
from wbox.gui.pages.knowledge import KnowledgePage  # noqa: F401
from wbox.gui.pages.troubleshoot import TroubleshootPage  # noqa: F401

__all__ = ["DoctorPage", "KnowledgePage", "TroubleshootPage"]
