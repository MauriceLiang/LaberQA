"""FAISS persistence and compatibility baseline for the current index."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import Settings
from app.rag.constants import CURRENT_SPLITTER_VERSION
from app.services.vector_store import VectorStoreService, VectorStoreSignatureMismatch


def test_fixed_embeddings_persist_and_reject_incompatible_configuration(
    tmp_path: Path,
    baseline_config: Settings,
    baseline_embedding: object,
) -> None:
    index_dir = tmp_path / "baseline-index"
    store = VectorStoreService(
        baseline_config,
        embedding_service=baseline_embedding,  # type: ignore[arg-type]
        index_dir=index_dir,
    )

    store.add([(101, [1.0, 0.0]), (102, [0.0, 1.0])])

    assert store.search([1.0, 0.0], 2) == [(101, 1.0), (102, 0.5)]
    metadata = json.loads((index_dir / "index_meta.json").read_text())
    assert metadata["embedding_model"] == "baseline-fixed-embedding"
    assert metadata["embedding_dimension"] == 2
    assert metadata["chunk_size"] == baseline_config.chunk_size
    assert metadata["chunk_overlap"] == baseline_config.chunk_overlap
    assert metadata["splitter_version"] == CURRENT_SPLITTER_VERSION

    reloaded = VectorStoreService(
        baseline_config,
        embedding_service=baseline_embedding,  # type: ignore[arg-type]
        index_dir=index_dir,
    )
    assert reloaded.load() is True
    assert reloaded.search([0.0, 1.0], 1) == [(102, 1.0)]

    changed_config = baseline_config.model_copy(
        update={"local_embedding_model": "baseline-other-embedding"}
    )
    incompatible = VectorStoreService(changed_config, index_dir=index_dir)
    with pytest.raises(VectorStoreSignatureMismatch):
        incompatible.load()
    assert incompatible.status == "incompatible"
