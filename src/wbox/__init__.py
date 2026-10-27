"""wbox —— 跨平台迁移白盒工作台核心包。"""

from .spec import SPEC_VERSION, SpecError, load, save, validate

__all__ = ["SPEC_VERSION", "SpecError", "load", "save", "validate"]
