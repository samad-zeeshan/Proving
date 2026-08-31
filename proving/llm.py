"""Optional local model calls through an OpenAI-compatible endpoint, and the two-pass token count.

Nothing here runs unless PROVING_LLM=1. The build, the tests and CI never need a model.
"""

from __future__ import annotations

import json
import os
import re

import httpx

BASE_URL = os.environ.get("PROVING_LLM_URL", "http://127.0.0.1:1234/v1").rstrip("/")
MODEL = os.environ.get("PROVING_LLM_MODEL", "qwen/qwen3.5-9b")


class ModelUnavailable(RuntimeError):
    pass


def enabled() -> bool:
    return os.environ.get("PROVING_LLM") == "1"


def require() -> None:
    if not enabled():
        raise ModelUnavailable("model calls are off. Set PROVING_LLM=1 with LM Studio running to record them")


def chat(messages: list[dict], *, model: str = MODEL, max_tokens: int = 200, schema: dict | None = None,
         timeout: float = 120.0) -> dict:
    require()
    body = {
        "model": model, "messages": messages, "temperature": 0, "max_tokens": max_tokens,
        # The served Qwen models think by default, which costs tens of seconds a call for nothing here.
        "reasoning_effort": "none",
    }
    if schema is not None:
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "out", "strict": True, "schema": schema}}
    r = httpx.post(f"{BASE_URL}/chat/completions", json=body, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    return {"content": data["choices"][0]["message"]["content"] or "", "usage": data.get("usage") or {},
            "model": data.get("model", model)}


def parse_json(content: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
    m = re.search(r"\{.*\}", text, flags=re.S)
    return json.loads(m.group(0) if m else text)


class ApproxCounter:
    """Offline stand-in used by tests: words and punctuation, with Arabic counted per two letters."""

    name = "approx"

    def count(self, messages: list[dict]) -> int:
        n = 0
        for m in messages:
            for tok in re.findall(r"\w+|[^\w\s]", m["content"]):
                n += max(1, len(tok) // 2) if re.search(r"[؀-ۿ]", tok) else 1
            n += 4
        return n


class ServerCounter:
    """Counts prompt tokens on the serving model without generating.

    The lmstudio SDK tokenizes the prompt after applying the model's own chat template, so the count
    matches what the endpoint bills. Without the SDK, a one-token request reads usage.prompt_tokens.
    """

    name = "server"

    def __init__(self, model: str = MODEL) -> None:
        self.model = model
        self._llm = None
        try:
            import lmstudio

            self._llm = lmstudio.llm(model)
            self.name = "lmstudio-tokenize"
        except Exception:  # noqa: BLE001 - fall back to the one-token request
            self.name = "one-token-request"

    def count(self, messages: list[dict]) -> int:
        if self._llm is not None:
            import lmstudio

            history = lmstudio.Chat()
            for m in messages:
                {"system": history.add_system_prompt, "user": history.add_user_message,
                 "assistant": history.add_assistant_response}[m["role"]](m["content"])
            return len(self._llm.tokenize(self._llm.apply_prompt_template(history)))
        return int(chat(messages, model=self.model, max_tokens=1)["usage"].get("prompt_tokens", 0))
