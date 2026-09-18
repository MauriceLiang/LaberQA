"""Document import and lifecycle baseline for the current implementation."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from app.core.config import Settings
from app.repositories.document_repository import DocumentRepository
from app.services.document_service import DocumentService
from app.services.file_storage import FileStorage
from app.services.retrieval import RetrievalService
from app.services.vector_store import VectorStoreNotInitialized, VectorStoreService

from .conftest import BASELINE_FILE_NAME, BASELINE_QUESTION


def test_upload_import_retrieve_and_delete_preserve_document_lifecycle(
    baseline_database: Path,
    baseline_config: Settings,
    baseline_embedding: object,
) -> None:
    repository = DocumentRepository(baseline_database)
    storage = FileStorage(baseline_config.upload_path)
    vector_store = VectorStoreService(
        baseline_config,
        embedding_service=baseline_embedding,  # type: ignore[arg-type]
        index_dir=baseline_config.faiss_path / "production",
    )
    service = DocumentService(
        baseline_config,
        repository=repository,
        file_storage=storage,
        embedding_service=baseline_embedding,  # type: ignore[arg-type]
        vector_store=vector_store,
    )

    uploaded = service.upload(
        io.BytesIO("第十条 建立劳动关系，应当订立书面劳动合同。".encode()),
        BASELINE_FILE_NAME,
        "text/plain",
    )
    document_id = int(uploaded["id"])
    stored_path = Path(uploaded["file_path"])

    assert uploaded["status"] == "PROCESSING"
    assert stored_path.is_file()

    service.import_document(document_id)

    imported = repository.get_document(document_id)
    chunks, total = repository.list_chunks(document_id)
    assert imported is not None
    assert imported["status"] == "SUCCESS"
    assert imported["chunk_count"] == 1
    assert total == 1
    assert chunks[0]["content"] == "第十条 建立劳动关系，应当订立书面劳动合同。"

    retrieval = RetrievalService(
        baseline_config,
        repository=repository,
        embedding_service=baseline_embedding,  # type: ignore[arg-type]
        vector_store=vector_store,
    )
    evidence = retrieval.retrieve(BASELINE_QUESTION)
    assert evidence[0]["chunk_id"] == chunks[0]["id"]
    assert evidence[0]["file_name"] == BASELINE_FILE_NAME

    deleted = service.delete_document(document_id)

    assert deleted["id"] == document_id
    assert repository.get_document(document_id) is None
    assert repository.list_chunks(document_id) == ([], 0)
    assert not stored_path.exists()
    with pytest.raises(VectorStoreNotInitialized):
        retrieval.retrieve(BASELINE_QUESTION)
