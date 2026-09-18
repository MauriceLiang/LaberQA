"""Factories and compatibility adapters for LangChain model providers."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import httpx
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import SecretStr

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


def build_embeddings(
    config: Settings = settings,
    *,
    http_client: Any | None = None,
) -> Embeddings:
    """Build the configured LangChain embedding implementation."""
    if config.embedding_provider == "local":
        from langchain_huggingface import HuggingFaceEmbeddings

        _configure_local_torch_runtime()
        return HuggingFaceEmbeddings(
            model_name=_resolve_local_model(config.local_embedding_model),
            model_kwargs={
                "device": _resolve_local_device(config.local_embedding_device)
            },
            encode_kwargs={
                "normalize_embeddings": config.embedding_normalize,
                "batch_size": config.embedding_batch_size,
            },
        )

    return CompatibleEmbeddings(
        model=config.embedding_api_model,
        api_key=config.embedding_api_key,
        base_url=config.embedding_base_url,
        http_client=http_client,
    )


def _resolve_local_model(model_name: str) -> str:
    local_path = Path(model_name).expanduser()
    if local_path.exists():
        return str(local_path)

    try:
        from huggingface_hub import snapshot_download
        from huggingface_hub.errors import LocalEntryNotFoundError

        return snapshot_download(model_name, local_files_only=True)
    except (LocalEntryNotFoundError, OSError):
        return model_name


def local_embedding_is_cached(config: Settings = settings) -> bool:
    """Return whether the configured local embedding model is on disk."""
    try:
        from huggingface_hub import snapshot_download
        from huggingface_hub.errors import LocalEntryNotFoundError

        model_name = config.local_embedding_model
        local_path = Path(model_name).expanduser()
        if local_path.exists():
            return True
        snapshot_download(model_name, local_files_only=True)
        return True
    except (ImportError, LocalEntryNotFoundError, OSError):
        return False


def _resolve_local_device(device: str) -> str:
    if device != "auto":
        return device

    import torch

    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _configure_local_torch_runtime() -> None:
    if sys.platform != "darwin":
        return

    import torch

    # PyTorch and faiss-cpu bundle different OpenMP runtimes on macOS. Keeping
    # PyTorch inference single-threaded prevents native worker-pool corruption.
    torch.set_num_threads(1)


class CompatibleEmbeddings(Embeddings):
    """OpenAI-compatible embeddings without model-specific tokenization.

    The configured service already receives bounded domain chunks. Sending
    those strings directly also keeps compatibility with providers that do not
    accept newer OpenAI SDK parameters such as ``encoding_format``.
    """

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.model = model
        self.openai_api_key = SecretStr(api_key)
        self.openai_api_base = _without_endpoint_suffix(base_url, "/embeddings")
        self._client = http_client

    @property
    def endpoint(self) -> str:
        return f"{self.openai_api_base}/embeddings"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        post = self._client.post if self._client is not None else httpx.post
        response = post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.openai_api_key.get_secret_value()}"
            },
            json={"model": self.model, "input": texts},
            timeout=60.0,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload["data"]
        if not isinstance(data, list) or len(data) != len(texts):
            raise ValueError("embedding response item count does not match request")
        ordered = sorted(data, key=lambda item: item.get("index", 0))
        return [item["embedding"] for item in ordered]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def _without_endpoint_suffix(base_url: str, suffix: str) -> str:
    normalized = base_url.rstrip("/")
    return normalized.removesuffix(suffix)
