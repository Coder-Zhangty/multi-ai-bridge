"""API-key-based adapter using OpenAI-compatible protocol.

Platforms that expose an OpenAI-compatible chat completions endpoint can
use this adapter as a faster, more reliable alternative to browser automation.

Platforms with incompatible APIs (Anthropic Messages, Google Gemini) are
excluded — they must use browser automation instead.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from app.models.schemas import now_iso

logger = logging.getLogger(__name__)

# Platforms whose APIs are NOT OpenAI-compatible — skip ApiAdapter for these.
# Claude uses Anthropic Messages API; Gemini uses generateContent.
_API_INCOMPATIBLE_PLATFORMS: set[str] = {"claude", "gemini"}

# Model name each platform reports / expects via API
PLATFORM_API_MODELS: dict[str, str] = {
    "deepseek": "deepseek-chat",
    "tongyi": "qwen-max",
    "kimi": "moonshot-v1-8k",
    "doubao": "ep-20241220180000-xxxxx",  # 豆包需在火山引擎控制台创建推理端点
    "chatgpt": "gpt-4o",
    "claude": "claude-3-5-sonnet-20241022",
    "gemini": "gemini-1.5-pro",
    "perplexity": "llama-3.1-sonar-large-128k-online",
}


class ApiAdapter:
    """Calls a platform via its OpenAI-compatible API using httpx.

    This is NOT a subclass of BaseAdapter (which expects a Playwright Page).
    Instead it provides the same logical interface but over HTTP.
    """

    def __init__(self, platform: str, api_key: str, api_base: str, model: str | None = None):
        self.platform = platform
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model or PLATFORM_API_MODELS.get(platform, "default")
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.api_base,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(180.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def chat(
        self,
        message: str,
        conversation_id: str | None = None,
        system_prompt: str | None = None,
    ) -> dict:
        """Non-streaming chat. Returns {conversation_id, reply}."""
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": message})

        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }

        client = await self._get_client()
        resp = await client.post("/chat/completions", json=body)
        resp.raise_for_status()
        data = resp.json()

        reply = data["choices"][0]["message"]["content"]
        cid = conversation_id or data.get("id", "")
        return {"conversation_id": cid, "reply": reply}

    async def chat_stream(self, message: str, conversation_id: str | None = None) -> AsyncGenerator[dict, None]:
        """Streaming chat. Yields {event: chunk|done, delta, conversation_id}."""
        messages: list[dict[str, str]] = [{"role": "user", "content": message}]

        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }

        client = await self._get_client()
        cid = conversation_id or ""

        async with client.stream("POST", "/chat/completions", json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    yield {"event": "done", "conversation_id": cid, "platform": self.platform}
                    return
                try:
                    chunk = json.loads(data_str)
                    delta = chunk["choices"][0].get("delta", {}).get("content", "")
                    if not cid and chunk.get("id"):
                        cid = chunk["id"]
                    if delta:
                        yield {"event": "chunk", "delta": delta, "conversation_id": cid, "platform": self.platform}
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

        yield {"event": "done", "conversation_id": cid, "platform": self.platform}

    # ----- compatibility with BaseAdapter interface -----

    async def send_message(self, **kwargs) -> None:
        raise NotImplementedError("ApiAdapter uses chat() / chat_stream() instead")

    async def wait_for_response(self, **kwargs) -> None:
        raise NotImplementedError("ApiAdapter uses chat() / chat_stream() instead")

    async def extract_reply(self, **kwargs) -> str:
        raise NotImplementedError("ApiAdapter uses chat() / chat_stream() instead")

    async def create_new_chat(self, **kwargs) -> str:
        return now_iso().replace(":", "-")

    async def is_logged_in(self, **kwargs) -> bool:
        return True  # API key is always "logged in"
