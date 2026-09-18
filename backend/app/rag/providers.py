"""Factories for LangChain chat-model and embedding providers.

The factories are additive during the migration. Existing services continue to
own the current HTTP and SentenceTransformer adapters until later batches move
their call sites to these interfaces.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from app.core.config import Settings, settings


def build_chat_model(config: Settings = settings) -> BaseChatModel:
    """Build the configured OpenAI-compatible LangChain chat model."""
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=config.llm_model,
        api_key=config.llm_api_key,
        base_url=_without_endpoint_suffix(config.llm_base_url, "/chat/completions"),
        streaming=True,
        use_responses_api=False,
    )


def build_embeddings(config: Settings = settings) -> Embeddings:
    """Build the configured LangChain embedding implementation."""
    if config.embedding_provider == "local":
        from langchain_huggingface import HuggingFaceEmbeddings

        return HuggingFaceEmbeddings(
            model_name=config.local_embedding_model,
            model_kwargs={"device": config.local_embedding_device},
            encode_kwargs={
                "normalize_embeddings": config.embedding_normalize,
                "batch_size": config.embedding_batch_size,
            },
        )

    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(
        model=config.embedding_api_model,
        api_key=config.embedding_api_key,
        base_url=_without_endpoint_suffix(config.embedding_base_url, "/embeddings"),
    )


def ensure_chat_model(provider: BaseChatModel | Any) -> BaseChatModel:
    """Return a ChatModel while keeping legacy async clients injectable.

    The compatibility path is only for callers that still provide the old
    ``complete``/``stream`` client. Production construction uses
    :func:`build_chat_model` directly.
    """

    if isinstance(provider, BaseChatModel):
        return provider
    return _LegacyLlmClientChatModel(provider)


class _LegacyLlmClientChatModel(BaseChatModel):
    """Adapt the pre-Batch-2 async client to LangChain's ChatModel interface."""

    client: Any

    def __init__(self, client: Any, **kwargs: Any) -> None:
        super().__init__(client=client, **kwargs)

    @property
    def _llm_type(self) -> str:
        return "legacy-openai-compatible"

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
        raise RuntimeError("Legacy LLM clients require the asynchronous interface")

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
            "role": _message_role(message),
            "content": _message_content(message),
        }
        for message in messages
    ]


def _message_role(message: BaseMessage) -> str:
    return {
        "human": "user",
        "ai": "assistant",
    }.get(message.type, message.type)


def _message_content(message: BaseMessage) -> str:
    content = message.content
    return (
        content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    )


def _without_endpoint_suffix(base_url: str, suffix: str) -> str:
    normalized = base_url.rstrip("/")
    return normalized.removesuffix(suffix)
