"""Factories for LangChain chat-model and embedding providers.

The factories are additive during the migration. Existing services continue to
own the current HTTP and SentenceTransformer adapters until later batches move
their call sites to these interfaces.
"""

from __future__ import annotations

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel

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


def _without_endpoint_suffix(base_url: str, suffix: str) -> str:
    normalized = base_url.rstrip("/")
    return normalized.removesuffix(suffix)
