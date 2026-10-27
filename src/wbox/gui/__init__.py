"""wbox.gui —— PySide6 桌面主控（跨平台迁移白盒工作台）。

硬规则（写死，不许绕）：
1. GUI 禁止直接 json.load/json.dump spec——一切经 wbox.session → wbox.spec。
2. 长任务（apktool/hvigor/下载）一律放 QThread，禁止卡死 UI 线程。
3. 全局异常钩子兜底：任何未捕获异常弹窗展示，不静默崩溃、不裸 traceback。
"""
