"""Small OpenAI-compatible chat-completions client used by RAG services."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

import httpx

from app.core.config import Settings, settings


class ModelUnavailableError(RuntimeError):
    """Raised when the configured chat model cannot complete a request."""


class LlmClient:
    def __init__(
        self,
        config: Settings = settings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        self._client = client

    @property
    def endpoint(self) -> str:
        base_url = self.config.llm_base_url.rstrip("/")
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> str:
        self._ensure_configured()
        payload: dict[str, Any] = {
            "model": self.config.llm_model,
            "messages": list(messages),
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if temperature is not None:
            payload["temperature"] = temperature
        try:
            if self._client is None:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(
                        self.endpoint, headers=self._headers(), json=payload
                    )
            else:
                response = await self._client.post(
                    self.endpoint, headers=self._headers(), json=payload
                )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("chat completion content is not text")
            return content
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise ModelUnavailableError("模型服务暂不可用") from exc

    async def stream(self, messages: Sequence[Mapping[str, str]]) -> AsyncIterator[str]:
        self._ensure_configured()
        payload = {
            "model": self.config.llm_model,
            "messages": list(messages),
            "stream": True,
        }
        try:
            if self._client is None:
                async with (
                    httpx.AsyncClient(timeout=None) as client,
                    client.stream(
                        "POST", self.endpoint, headers=self._headers(), json=payload
                    ) as response,
                ):
                    async for content in self._stream_content(response):
                        yield content
            else:
                async with self._client.stream(
                    "POST", self.endpoint, headers=self._headers(), json=payload
                ) as response:
                    async for content in self._stream_content(response):
                        yield content
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise ModelUnavailableError("模型服务暂不可用") from exc

    async def _stream_content(self, response: httpx.Response) -> AsyncIterator[str]:
        response.raise_for_status()
        has_content = False
        has_done = False
        async for line in response.aiter_lines():
            if not line or not line.startswith("data:"):
                continue
            data = line.removeprefix("data:").strip()
            if data == "[DONE]":
                has_done = True
                break
            payload = json.loads(data)
            if not isinstance(payload, dict):
                raise TypeError("chat stream payload is not an object")
            if payload.get("error"):
                raise ModelUnavailableError("模型服务暂不可用")
            choices = payload.get("choices", [])
            if not isinstance(choices, list):
                raise TypeError("chat stream choices is not a list")
            if not choices:
                continue
            choice = choices[0]
            if not isinstance(choice, dict):
                raise TypeError("chat stream choice is not an object")
            delta = choice.get("delta", {})
            if not isinstance(delta, dict):
                raise TypeError("chat stream delta is not an object")
            content = delta.get("content")
            if content is not None:
                if not isinstance(content, str):
                    raise ValueError("chat stream content is not text")
                if content:
                    has_content = True
                    yield content
        if not has_done:
            raise ModelUnavailableError("模型回答流意外结束")
        if not has_content:
            raise ModelUnavailableError("模型未返回回答内容")

    def _ensure_configured(self) -> None:
        if not all(
            (self.config.llm_api_key, self.config.llm_base_url, self.config.llm_model)
        ):
            raise ModelUnavailableError("LLM_API_KEY、LLM_BASE_URL、LLM_MODEL 尚未配置")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.llm_api_key}",
            "Content-Type": "application/json",
        }
