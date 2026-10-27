"""wbox.gui.threads —— 后台线程登记表：保证"进程退出时没有线程还活着"。

存在理由（2026-10-27，反复踩坑）：离屏冒烟偶尔出现退出码 127——不是脚本失败，
而是解释器收尾时某个 QThread 还在跑（典型是卡在 `java -version` / `hdc` 子进程上）。
逐个页面手写 `wait` 很脆弱：新增一个后台任务就可能漏一处，而且"漏了"只在
偶发时才暴露（我实测同一份代码连跑两次，一次 0 一次 127）。

所以把"谁在跑"收敛到一张登记表：所有 QThread 创建后调一次 `track_thread()`，
窗口关闭 / 脚本收尾时统一 `wait_all_threads()`。宁可多等 3 秒，也不要出 127。
"""

from __future__ import annotations

from PySide6.QtCore import QThread

_TRACKED: list[QThread] = []


def track_thread(thread: QThread) -> QThread:
    """登记一个后台线程（幂等），结束后自动从表里移除。返回原对象便于链式写。"""
    if thread in _TRACKED:
        return thread
    _TRACKED.append(thread)

    def _forget() -> None:
        if thread in _TRACKED:
            _TRACKED.remove(thread)

    thread.finished.connect(_forget)
    return thread


def running_threads() -> list[QThread]:
    """当前仍在运行的已登记线程（排障用）。"""
    return [th for th in _TRACKED if th.isRunning()]


def wait_all_threads(msec_per_thread: int = 8000) -> list[QThread]:
    """等待所有已登记线程结束，返回仍未结束的那些（正常情况下应为空）。"""
    stragglers: list[QThread] = []
    for thread in list(_TRACKED):
        try:
            if thread.isRunning():
                if not thread.wait(msec_per_thread):
                    stragglers.append(thread)
        except RuntimeError:      # 底层 C++ 对象已销毁
            continue
    return stragglers
