"""Small LangChain-native test doubles shared by service tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult


class AsyncClientChatModel(BaseChatModel):
    """Adapt a test client's async complete/stream methods to BaseChatModel."""

    client: Any

    def __init__(self, client: Any, **kwargs: Any) -> None:
        super().__init__(client=client, **kwargs)

    @property
    def _llm_type(self) -> str:
        return "test-async-client"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._agenerate(messages, **kwargs))
        raise RuntimeError("AsyncClientChatModel requires ainvoke")

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager
        request: dict[str, Any] = {
            "messages": _message_dicts(messages),
            "json_mode": bool(kwargs.get("response_format")),
        }
        if kwargs.get("temperature") is not None:
            request["temperature"] = kwargs["temperature"]
        content = await self.client.complete(**request)
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=content))]
        )

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        del stop, run_manager, kwargs
        async for token in self.client.stream(_message_dicts(messages)):
            yield ChatGenerationChunk(message=AIMessageChunk(content=token))


def _message_dicts(messages: list[BaseMessage]) -> list[dict[str, str]]:
    return [
        {
            "role": {"human": "user", "ai": "assistant"}.get(
                message.type, message.type
            ),
            "content": (
                message.content
                if isinstance(message.content, str)
                else str(message.content)
            ),
        }
        for message in messages
    ]
