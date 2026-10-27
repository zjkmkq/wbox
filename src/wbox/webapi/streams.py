"""wbox.webapi.streams —— SSE 事件桥：后台线程干活，HTTP 流式吐事件。

用途（写死）：extract / assemble / build / ai 生成都是长任务，日志必须
逐行进前端。模式固定为：
    bus = LogBus()
    threading.Thread(target=worker, args=(bus,), daemon=True).start()
    return StreamingResponse(bus.events(), media_type="text/event-stream")

事件协议（前端 EventSource 直接吃）：
    data: {"t":"log","line":"..."}
    data: {"t":"step","name":"解析资源与代码骨架…"}
    data: {"t":"progress","value":0.42}
    data: {"t":"done","ok":true,"summary":"..."}
    data: {"t":"error","message":"..."}
"""

from __future__ import annotations

import json
import queue
import threading


class LogBus:
    """线程安全的事件总线：worker 调 put_*，SSE 生成器 events() 逐条吐。"""

    def __init__(self) -> None:
        self._q: queue.Queue[dict | None] = queue.Queue()
        self._done = threading.Event()

    # ------------------------------------------------------------ worker 侧

    def put_log(self, line: str) -> None:
        self._q.put({"t": "log", "line": str(line).rstrip("\n")})

    def put_step(self, name: str) -> None:
        self._q.put({"t": "step", "name": str(name)})

    def put_progress(self, value: float) -> None:
        self._q.put({"t": "progress", "value": max(0.0, min(1.0, float(value)))})

    def put_done(self, ok: bool, summary: str = "", extra: dict | None = None) -> None:
        ev = {"t": "done", "ok": bool(ok), "summary": summary}
        if extra:
            ev.update(extra)
        self._q.put(ev)
        self._q.put(None)          # 哨兵：流结束
        self._done.set()

    def put_error(self, message: str) -> None:
        self._q.put({"t": "error", "message": str(message)})
        self._q.put(None)
        self._done.set()

    # ------------------------------------------------------------ HTTP 侧

    def events(self):
        """SSE 生成器：阻塞等事件，收到哨兵（None）即结束流。"""
        while True:
            try:
                ev = self._q.get(timeout=1.0)
            except queue.Empty:
                # 心跳注释行：防代理/浏览器掐空闲连接
                yield ": keep-alive\n\n"
                continue
            if ev is None:
                return
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

    @property
    def finished(self) -> bool:
        return self._done.is_set()


def run_worker(bus: LogBus, fn, *args, **kwargs) -> threading.Thread:
    """起 daemon 线程跑 fn(bus, *args)；fn 内部必须自行 put_done/put_error。

    兜底：fn 抛了没见过的异常也要收口成 error 事件，绝不让 SSE 悬挂。
    """
    def _wrap() -> None:
        try:
            fn(bus, *args, **kwargs)
        except BaseException as e:  # noqa: BLE001  流式通道内一切失败都要显式上报
            if not bus.finished:
                bus.put_error(f"{type(e).__name__}: {e}")
    th = threading.Thread(target=_wrap, daemon=True)
    th.start()
    return th
