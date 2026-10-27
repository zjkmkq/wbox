"""wbox.aiclient —— 「填上」步 API 直连：OpenAI 兼容客户端。

硬规则（写死，不许绕）：
1. 只走 OpenAI 兼容的 /chat/completions 协议（base_url 用户配置），不绑定
   任何厂商；key 只从应用配置读，不落日志、不进任务包。
2. 流式输出（SSE），逐段回调；超时/断流/限流都要给出人话错误，不抛裸异常
   给 GUI。
3. 生成结果由调用方负责校验与落盘；本模块只负责"把 prompt 发出去、把
   文本收回来"。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

BROWSER_UA = "WBox/1.0 (HarmonyOS Migration Workbench)"

DEFAULT_TIMEOUT = 120  # 秒；生成整工程可能较久


@dataclass
class ChatResult:
    ok: bool
    text: str = ""
    error: str = ""
    model: str = ""
    usage: dict | None = None


class AIClient:
    def __init__(self, base_url: str, api_key: str, model: str,
                 timeout: int = DEFAULT_TIMEOUT) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    # ------------------------------------------------------------ 协议

    def chat(self, prompt: str, system: str = "", temperature: float = 0.2,
             on_delta=None) -> ChatResult:
        """非流式；on_delta 可传 None。"""
        return self._send(prompt, system, temperature, stream=False, on_delta=on_delta)

    def chat_stream(self, prompt: str, system: str = "", temperature: float = 0.2,
                    on_delta=None) -> ChatResult:
        return self._send(prompt, system, temperature, stream=True, on_delta=on_delta)

    def _send(self, prompt: str, system: str, temperature: float,
              stream: bool, on_delta) -> ChatResult:
        if not self.configured:
            return ChatResult(False, error="AI 未配置：请在设置里填 base_url / api_key / model")
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }
        url = f"{self.base_url}/chat/completions"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": BROWSER_UA,
            },
            method="POST",
        )
        try:
            if stream:
                return self._read_stream(req, on_delta)
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            choice = (data.get("choices") or [{}])[0]
            text = str(choice.get("message", {}).get("content", ""))
            return ChatResult(True, text=text, model=str(data.get("model", self.model)),
                              usage=data.get("usage"))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")[:300]
            except OSError:
                pass
            return ChatResult(False, error=f"API 返回 HTTP {e.code}：{body}")
        except urllib.error.URLError as e:
            return ChatResult(False, error=f"网络错误：{e.reason}")
        except (json.JSONDecodeError, OSError, KeyError) as e:
            return ChatResult(False, error=f"响应解析失败：{e}")

    def _read_stream(self, req, on_delta) -> ChatResult:
        parts: list[str] = []
        model = self.model
        usage = None
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    model = str(chunk.get("model", model))
                    if chunk.get("usage"):
                        usage = chunk["usage"]
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        piece = delta.get("content")
                        if piece:
                            parts.append(piece)
                            if on_delta:
                                on_delta(piece)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")[:300]
            except OSError:
                pass
            return ChatResult(False, error=f"API 返回 HTTP {e.code}：{body}")
        except urllib.error.URLError as e:
            return ChatResult(False, error=f"网络错误：{e.reason}")
        return ChatResult(True, text="".join(parts), model=model, usage=usage)


def client_from_config(cfg: dict) -> AIClient:
    ai = cfg.get("ai", {})
    return AIClient(ai.get("base_url", ""), ai.get("api_key", ""), ai.get("model", ""))
