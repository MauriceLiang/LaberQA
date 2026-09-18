import logging
import math
from collections.abc import Callable
from functools import lru_cache
from typing import Any, Protocol

import httpx
from langchain_core.embeddings import Embeddings

from app.core.config import Settings, settings
from app.rag.providers import build_embeddings
from app.schemas.contracts import EmbeddingSignature

logger = logging.getLogger(__name__)


class EmbeddingUnavailableError(RuntimeError):
    """Raised when the configured embedding provider cannot encode text."""


class EmbeddingDimensionUnknown(RuntimeError):
    """Raised when an API provider has not returned a vector yet."""


class EmbeddingProvider(Protocol):
    name: str
    model: str
    normalize_embeddings: bool
    dimension: int | None

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


@lru_cache(maxsize=4)
def _load_model(model_name: str, device: str) -> Any:
    import torch
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError
    from sentence_transformers import SentenceTransformer

    if device == "auto":
        if torch.cuda.is_available():
            device = "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"

    try:
        model_path = snapshot_download(model_name, local_files_only=True)
    except (LocalEntryNotFoundError, OSError):
        model_path = model_name
    return SentenceTransformer(model_path, device=device)


class LocalEmbeddingProvider:
    name = "local"

    def __init__(self, config: Settings = settings) -> None:
        self.model = config.local_embedding_model
        self.normalize_embeddings = config.embedding_normalize
        self.batch_size = config.embedding_batch_size
        self.device = config.local_embedding_device
        self.dimension: int | None = None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        _validate_texts(texts)
        try:
            model = _load_model(self.model, self.device)
            vectors = model.encode(
                texts,
                batch_size=self.batch_size,
                normalize_embeddings=self.normalize_embeddings,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            result = _validate_vectors(vectors.tolist(), len(texts))
            self.dimension = len(result[0])
            return result
        except EmbeddingUnavailableError:
            raise
        except Exception as exc:
            logger.exception("Local embedding provider failed")
            raise EmbeddingUnavailableError("本地向量模型暂不可用") from exc


class ApiEmbeddingProvider:
    name = "api"

    def __init__(
        self,
        config: Settings = settings,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = config.embedding_api_model
        self.normalize_embeddings = config.embedding_normalize
        self.base_url = config.embedding_base_url.rstrip("/")
        self.api_key = config.embedding_api_key
        self.dimension: int | None = None
        self._client = client

    @property
    def endpoint(self) -> str:
        if self.base_url.endswith("/embeddings"):
            return self.base_url
        return f"{self.base_url}/embeddings"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        _validate_texts(texts)
        try:
            post = self._client.post if self._client is not None else httpx.post
            response = post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "input": texts},
                timeout=60.0,
            )
            response.raise_for_status()
            payload = response.json()
            data = payload["data"]
            if not isinstance(data, list) or len(data) != len(texts):
                raise ValueError("embedding response item count does not match request")
            ordered = sorted(data, key=lambda item: item.get("index", 0))
            vectors = [item["embedding"] for item in ordered]
            result = _validate_vectors(vectors, len(texts))
            if self.normalize_embeddings:
                result = [_normalize(vector) for vector in result]
            self.dimension = len(result[0])
            return result
        except Exception as exc:
            logger.warning("API embedding provider failed: %s", type(exc).__name__)
            raise EmbeddingUnavailableError("远程向量服务暂不可用") from exc


class _LangChainEmbeddingProvider:
    """Expose a LangChain Embeddings object with index-signature metadata."""

    def __init__(self, config: Settings, embeddings: Embeddings) -> None:
        self.name = config.embedding_provider
        self.model = config.embedding_model
        self.normalize_embeddings = config.embedding_normalize
        self.embeddings = embeddings
        self.dimension: int | None = None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        _validate_texts(texts)
        try:
            vectors = self.embeddings.embed_documents(texts)
            result = _validate_vectors(vectors, len(texts))
            if self.normalize_embeddings:
                result = [_normalize(vector) for vector in result]
            self.dimension = len(result[0])
            return result
        except EmbeddingUnavailableError:
            raise
        except Exception as exc:
            logger.exception("LangChain embedding provider failed")
            raise EmbeddingUnavailableError("向量服务暂不可用") from exc

    def embed_query(self, text: str) -> list[float]:
        _validate_texts([text])
        try:
            vector = _validate_vectors([self.embeddings.embed_query(text)], 1)[0]
            if self.normalize_embeddings:
                vector = _normalize(vector)
            self.dimension = len(vector)
            return vector
        except EmbeddingUnavailableError:
            raise
        except Exception as exc:
            logger.exception("LangChain embedding provider failed")
            raise EmbeddingUnavailableError("向量服务暂不可用") from exc


class _LazyEmbeddings(Embeddings):
    """Defer provider construction until the first actual embedding call."""

    def __init__(self, factory: Callable[[], Embeddings]) -> None:
        self._factory = factory
        self._inner: Embeddings | None = None

    @property
    def inner(self) -> Embeddings:
        if self._inner is None:
            self._inner = self._factory()
        return self._inner

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.inner.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self.inner.embed_query(text)


class EmbeddingService(Embeddings):
    """Embedding facade that preserves signatures while using LangChain APIs.

    ``provider`` remains available for deterministic tests and compatibility
    callers. The default path constructs a LangChain ``Embeddings`` provider
    lazily through :func:`app.rag.providers.build_embeddings`.
    """

    def __init__(
        self,
        config: Settings = settings,
        *,
        provider: EmbeddingProvider | None = None,
        embeddings: Embeddings | None = None,
        api_client: httpx.Client | None = None,
    ) -> None:
        if provider is not None and embeddings is not None:
            raise ValueError("provider 与 embeddings 不能同时传入")
        if provider is not None:
            self.provider = provider
            self.embeddings = None
            return

        backend = embeddings or _LazyEmbeddings(
            lambda: build_embeddings(config, http_client=api_client)
        )
        self.embeddings = backend
        self.provider = _LangChainEmbeddingProvider(config, backend)

    @property
    def embedding_dimension(self) -> int | None:
        return self.provider.dimension

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.provider.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        embed_query = getattr(self.provider, "embed_query", None)
        if embed_query is None:
            return self.embed_documents([text])[0]
        return embed_query(text)

    def signature(self, embedding_dimension: int | None = None) -> EmbeddingSignature:
        dimension = embedding_dimension or self.embedding_dimension
        if dimension is None and isinstance(self.provider, LocalEmbeddingProvider):
            try:
                dimension = int(
                    _load_model(
                        self.provider.model, self.provider.device
                    ).get_sentence_embedding_dimension()
                )
                self.provider.dimension = dimension
            except Exception as exc:
                raise EmbeddingUnavailableError("本地向量模型暂不可用") from exc
        if dimension is None and isinstance(self.provider, _LangChainEmbeddingProvider):
            try:
                dimension = len(self.provider.embed_query("维度探测"))
            except EmbeddingUnavailableError:
                raise
            except Exception as exc:
                raise EmbeddingUnavailableError("向量服务暂不可用") from exc
        if dimension is None:
            raise EmbeddingDimensionUnknown("Embedding 维度尚未从 Provider 获取")
        return EmbeddingSignature(
            embedding_provider=self.provider.name,
            embedding_model=self.provider.model,
            embedding_dimension=dimension,
            normalize_embeddings=self.provider.normalize_embeddings,
        )


def _validate_texts(texts: list[str]) -> None:
    if not texts or any(
        not isinstance(text, str) or not text.strip() for text in texts
    ):
        raise ValueError("Embedding 输入不能为空")


def _validate_vectors(vectors: list[Any], expected_count: int) -> list[list[float]]:
    if len(vectors) != expected_count:
        raise ValueError("embedding response item count does not match request")
    result: list[list[float]] = []
    dimension: int | None = None
    for vector in vectors:
        values = [float(value) for value in vector]
        if not values or any(not math.isfinite(value) for value in values):
            raise ValueError("embedding response contains an invalid vector")
        if dimension is None:
            dimension = len(values)
        elif len(values) != dimension:
            raise ValueError("embedding response dimensions do not match")
        result.append(values)
    return result


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        raise ValueError("embedding response contains a zero vector")
    return [value / norm for value in vector]


def local_embedding_is_cached() -> bool:
    try:
        from huggingface_hub import snapshot_download
        from huggingface_hub.errors import LocalEntryNotFoundError

        snapshot_download(settings.local_embedding_model, local_files_only=True)
        return True
    except (ImportError, LocalEntryNotFoundError, OSError):
        return False
