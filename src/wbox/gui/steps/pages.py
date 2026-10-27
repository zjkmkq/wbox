"""六步页面注册：六步全部实跑版（拆→画拼图→判断→填上→装配→补缝）。"""

from wbox.gui.steps import StepPage, register
from wbox.gui.steps.extract_step import ExtractStep  # noqa: F401  注册 ① 拆
from wbox.gui.steps.plan_step import PlanStep  # noqa: F401  注册 ② 画拼图
from wbox.gui.steps.decide_step import DecideStep  # noqa: F401  注册 ③ 判断
from wbox.gui.steps.fill_step import FillStep  # noqa: F401  注册 ④ 填上
from wbox.gui.steps.assemble_step import AssembleStep  # noqa: F401  注册 ⑤ 装配
from wbox.gui.steps.seal_step import SealStep  # noqa: F401  注册 ⑥ 补缝
