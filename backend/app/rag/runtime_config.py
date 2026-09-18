"""Stable runtime metadata captured by evaluation and retrieval experiments."""

from __future__ import annotations

from functools import lru_cache
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from typing import Any

from app.core.config import Settings
from app.rag.constants import CURRENT_SPLITTER_VERSION
from app.services.rerank import DEFAULT_RERANK_MODEL

DEFAULT_CHAT_PROVIDER = "langchain_openai.ChatOpenAI"
DEFAULT_SPLITTER_TYPE = "app.rag.splitters.LegalTextSplitter"
DEFAULT_VECTORSTORE_TYPE = "langchain_community.vectorstores.FAISS"
DEFAULT_RETRIEVAL_TYPE = "similarity"
DEFAULT_PROMPT_VERSION = "labor_langchain_v1"


@lru_cache(maxsize=1)
def langchain_version() -> str:
    """Return the installed LangChain core version for reproducibility."""

    try:
        return package_version("langchain-core")
    except PackageNotFoundError:
        return "unknown"


def runtime_config_snapshot(
    config: Settings, *, prompt_version: str = DEFAULT_PROMPT_VERSION
) -> dict[str, Any]:
    """Build the stable LangChain portion of an execution configuration."""

    return {
        "langchain_version": langchain_version(),
        "chat_provider": DEFAULT_CHAT_PROVIDER,
        "llm_model": config.llm_model,
        "embedding_provider": config.embedding_provider,
        "embedding_model": config.embedding_model,
        "embedding_normalize": config.embedding_normalize,
        "splitter_type": DEFAULT_SPLITTER_TYPE,
        "splitter_version": CURRENT_SPLITTER_VERSION,
        "vectorstore_type": DEFAULT_VECTORSTORE_TYPE,
        "retrieval_type": DEFAULT_RETRIEVAL_TYPE,
        "rerank_model": (DEFAULT_RERANK_MODEL if config.rerank_enabled else None),
        "prompt_version": prompt_version,
    }
