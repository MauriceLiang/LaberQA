import json
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services import vector_store as vector_store_module
from app.services.vector_store import (
    VectorStoreNotInitialized,
    VectorStorePersistenceError,
    VectorStoreService,
    VectorStoreSignatureMismatch,
)


def make_config(model: str = "test-embedding-model") -> Settings:
    return Settings(
        _env_file=None,
        local_embedding_model=model,
        embedding_provider="local",
        faiss_dir=Path("/unused-by-explicit-index-dir"),
    )


def test_add_search_remove_and_reload(tmp_path: Path) -> None:
    store = VectorStoreService(make_config(), index_dir=tmp_path / "production")

    assert store.load() is False
    store.add([(101, [1.0, 0.0]), (102, [0.0, 1.0])])
    assert store.status == "ready"
    assert store.search([4.0, 0.0], 2) == [(101, 1.0), (102, 0.5)]

    meta = json.loads((tmp_path / "production" / "index_meta.json").read_text())
    assert meta["embedding_provider"] == "local"
    assert meta["embedding_model"] == "test-embedding-model"
    assert meta["embedding_dimension"] == 2
    assert meta["normalize_embeddings"] is True
    assert meta["chunk_size"] == 600
    assert meta["chunk_overlap"] == 100
    assert meta["created_at"]

    reloaded = VectorStoreService(make_config(), index_dir=tmp_path / "production")
    assert reloaded.load() is True
    assert reloaded.search([1.0, 0.0], 1) == [(101, 1.0)]
    reloaded.remove([101])
    assert reloaded.search([1.0, 0.0], 2) == [(102, 0.5)]


def test_signature_mismatch_is_exposed_instead_of_loading_index(
    tmp_path: Path,
) -> None:
    index_dir = tmp_path / "production"
    VectorStoreService(make_config(), index_dir=index_dir).add([(1, [1.0, 0.0])])

    incompatible = VectorStoreService(make_config("changed-model"), index_dir=index_dir)
    with pytest.raises(VectorStoreSignatureMismatch):
        incompatible.load()
    assert incompatible.status == "incompatible"
    assert incompatible.is_signature_compatible() is False
    with pytest.raises(VectorStoreSignatureMismatch):
        incompatible.add([(2, [0.0, 1.0])])

    reloaded = VectorStoreService(make_config(), index_dir=index_dir)
    assert reloaded.load() is True
    assert reloaded.search([1.0, 0.0], 10) == [(1, 1.0)]


def test_query_dimension_mismatch_and_empty_rebuild(tmp_path: Path) -> None:
    store = VectorStoreService(make_config(), index_dir=tmp_path / "production")
    store.add([(1, [1.0, 0.0])])

    with pytest.raises(VectorStoreSignatureMismatch):
        store.search([1.0, 0.0, 0.0], 1)

    assert store.rebuild_from_success_chunks([]) is False
    assert store.load() is False
    with pytest.raises(VectorStoreNotInitialized):
        store.search([1.0], 1)


def test_empty_persisted_index_is_not_initialized_but_still_compatible(
    tmp_path: Path,
) -> None:
    index_dir = tmp_path / "production"
    store = VectorStoreService(make_config(), index_dir=index_dir)
    store.add([(1, [1.0, 0.0])])
    store.remove([1])
    assert store.status == "not_initialized"

    reloaded = VectorStoreService(make_config(), index_dir=index_dir)
    assert reloaded.load() is False
    assert reloaded.status == "not_initialized"
    assert reloaded.is_signature_compatible() is True


def test_rebuild_replaces_all_ids_and_rejects_invalid_vectors(tmp_path: Path) -> None:
    store = VectorStoreService(make_config(), index_dir=tmp_path / "production")
    store.add([(1, [1.0, 0.0])])
    assert store.rebuild_from_success_chunks([(2, [0.0, 1.0])]) is True
    assert store.search([0.0, 1.0], 10) == [(2, 1.0)]

    with pytest.raises(ValueError):
        store.add([(3, [0.0, 0.0])])


def test_failed_metadata_replace_restores_previous_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index_dir = tmp_path / "production"
    store = VectorStoreService(make_config(), index_dir=index_dir)
    store.add([(1, [1.0, 0.0])])

    original_replace = vector_store_module.os.replace
    failed_once = False

    def fail_metadata_replace_once(source: object, destination: object) -> None:
        nonlocal failed_once
        if Path(destination) == index_dir / "index_meta.json" and not failed_once:
            failed_once = True
            raise OSError("simulated metadata replacement failure")
        original_replace(source, destination)

    monkeypatch.setattr(vector_store_module.os, "replace", fail_metadata_replace_once)
    with pytest.raises(VectorStorePersistenceError):
        store.add([(2, [0.0, 1.0])])

    assert store.search([1.0, 0.0], 10) == [(1, 1.0)]
    reloaded = VectorStoreService(make_config(), index_dir=index_dir)
    assert reloaded.load() is True
    assert reloaded.search([1.0, 0.0], 10) == [(1, 1.0)]
