"""Runtime errors shared by LangChain-backed RAG infrastructure."""

from __future__ import annotations


class ModelUnavailableError(RuntimeError):
    """Raised when the configured chat model cannot complete a request."""


class EmbeddingUnavailableError(RuntimeError):
    """Raised when the configured embedding provider cannot encode text."""


class EmbeddingDimensionUnknown(RuntimeError):
    """Raised when an embedding provider has not returned a vector yet."""
