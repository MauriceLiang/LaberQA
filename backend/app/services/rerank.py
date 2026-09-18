"""Optional local cross-encoder reranking with retrieval-order fallback."""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from functools import lru_cache
from typing import Any, Protocol

from app.core.config import Settings, settings

logger = logging.getLogger(__name__)
DEFAULT_RERANK_MODEL = "BAAI/bge-reranker-base"
_DEFAULT_MODEL = DEFAULT_RERANK_MODEL


class CrossEncoder(Protocol):
    def predict(self, sentences: list[tuple[str, str]]) -> Sequence[float]: ...


@lru_cache(maxsize=2)
def _load_cross_encoder(model_name: str) -> Any:
    from huggingface_hub import snapshot_download
    from sentence_transformers import CrossEncoder as SentenceCrossEncoder

    model_path = snapshot_download(model_name, local_files_only=True)
    return SentenceCrossEncoder(model_path)


class RerankService:
    def __init__(
        self,
        config: Settings = settings,
        *,
        model: CrossEncoder | None = None,
    ) -> None:
        self.config = config
        self.model = model

    def rerank(
        self, query: str, evidence: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if not evidence:
            return []
        try:
            model = self.model or _load_cross_encoder(_DEFAULT_MODEL)
            logits = model.predict([(query, str(item["content"])) for item in evidence])
            if len(logits) != len(evidence):
                raise ValueError("reranker result count does not match evidence count")
            ranked = [
                (index, item, _sigmoid(float(logit)))
                for index, (item, logit) in enumerate(
                    zip(evidence, logits, strict=True)
                )
            ]
            ranked.sort(key=lambda result: (-result[2], result[0]))
            return [
                {
                    **item,
                    "score": score,
                    "rerank_score": score,
                    "rank_no": rank_no,
                }
                for rank_no, (_, item, score) in enumerate(
                    ranked[: self.config.rerank_top_n], start=1
                )
            ]
        except Exception:
            logger.warning(
                "Rerank failed; retaining vector retrieval order", exc_info=True
            )
            return [dict(item) for item in evidence]


def _sigmoid(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("reranker returned a non-finite score")
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)
