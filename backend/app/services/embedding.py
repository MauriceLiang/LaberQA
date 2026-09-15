from functools import lru_cache
from typing import Any

from app.core.config import settings


@lru_cache(maxsize=1)
def _load_model() -> Any:
    import torch
    from sentence_transformers import SentenceTransformer

    device = settings.local_embedding_device
    if device == "auto":
        if torch.cuda.is_available():
            device = "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"

    return SentenceTransformer(settings.local_embedding_model, device=device)


class EmbeddingService:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts or any(not text.strip() for text in texts):
            raise ValueError("Embedding 输入不能为空")

        vectors = _load_model().encode(
            texts,
            batch_size=settings.embedding_batch_size,
            normalize_embeddings=settings.embedding_normalize,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vectors.tolist()

    def embed_query(self, text: str) -> list[float]:
        if not text.strip():
            raise ValueError("Embedding 输入不能为空")
        return self.embed_documents([text])[0]


def local_embedding_is_cached() -> bool:
    try:
        from huggingface_hub import snapshot_download
        from huggingface_hub.errors import LocalEntryNotFoundError

        snapshot_download(settings.local_embedding_model, local_files_only=True)
        return True
    except (ImportError, LocalEntryNotFoundError, OSError):
        return False
