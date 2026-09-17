import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from app.repositories.document_repository import DocumentRepository

SCHEMA_PATH = Path(__file__).parents[1] / "app" / "core" / "schema.sql"


@pytest.fixture
def repository(tmp_path: Path) -> DocumentRepository:
    database_path = tmp_path / "documents.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return DocumentRepository(database_path)


def test_document_filtering_pagination_and_chunk_lifecycle(
    repository: DocumentRepository,
) -> None:
    first = repository.create_document(
        file_name="劳动合同.pdf", file_type="pdf", file_path="/tmp/first.pdf"
    )
    second = repository.create_document(
        file_name="工资说明.txt", file_type="txt", file_path="/tmp/second.txt"
    )
    repository.update_document(first["id"], status="SUCCESS", chunk_count=2)
    repository.insert_chunks(
        first["id"],
        [
            {"chunk_no": 1, "content": "第一段"},
            {"chunk_no": 2, "content": "第二段"},
        ],
    )
    repository.insert_chunks(
        second["id"], [{"chunk_no": 1, "content": "工资百分比 100%"}]
    )

    documents, total = repository.list_documents(
        page=1, size=1, status="SUCCESS", keyword="合同"
    )
    assert total == 1
    assert documents[0]["id"] == first["id"]

    chunks, chunk_total = repository.list_chunks(first["id"], page=2, size=1)
    assert chunk_total == 2
    assert chunks[0]["content"] == "第二段"
    assert chunks[0]["vector_key"] == f"chunk:{chunks[0]['id']}"

    successful_chunks = repository.list_success_chunks()
    assert [chunk["content"] for chunk in successful_chunks] == ["第一段", "第二段"]
    assert (
        repository.update_document(
            first["id"], status="FAILED", error_message="导入失败"
        )["error_message"]
        == "导入失败"
    )
    assert repository.list_success_chunks() == []


def test_foreign_keys_are_enabled_for_every_repository_connection(
    repository: DocumentRepository,
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        repository.insert_chunks(999999, [{"chunk_no": 1, "content": "孤立 chunk"}])


def test_chunk_insert_is_transactional_on_unique_number_conflict(
    repository: DocumentRepository,
) -> None:
    document = repository.create_document(
        file_name="file.txt", file_type="txt", file_path="/tmp/file.txt"
    )
    with pytest.raises(sqlite3.IntegrityError):
        repository.insert_chunks(
            document["id"],
            [
                {"chunk_no": 1, "content": "valid first"},
                {"chunk_no": 1, "content": "duplicate"},
            ],
        )

    chunks, total = repository.list_chunks(document["id"])
    assert total == 0
    assert chunks == []


def test_delete_document_removes_chunks_and_citations_in_one_transaction(
    repository: DocumentRepository,
) -> None:
    document = repository.create_document(
        file_name="待删除.txt", file_type="txt", file_path="/tmp/to-delete.txt"
    )
    chunks = repository.insert_chunks(
        document["id"],
        [
            {"chunk_no": 1, "content": "第一段"},
            {"chunk_no": 2, "content": "第二段"},
        ],
    )
    session_id = str(uuid4())
    with repository._connection() as connection:
        connection.execute(
            "INSERT INTO session (id, title) VALUES (?, ?)", (session_id, "测试")
        )
        cursor = connection.execute(
            "INSERT INTO message (session_id, role, content) VALUES (?, ?, ?)",
            (session_id, "assistant", "回答"),
        )
        connection.execute(
            """
            INSERT INTO citation (
                message_id, chunk_id, score, retrieval_score, rank_no
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (cursor.lastrowid, chunks[0]["id"], 0.9, 0.8, 1),
        )

    deleted = repository.delete_document(document["id"])

    assert deleted is not None
    assert deleted["document"]["id"] == document["id"]
    assert deleted["chunk_ids"] == [chunk["id"] for chunk in chunks]
    assert repository.get_document(document["id"]) is None
    assert repository.list_chunks(document["id"]) == ([], 0)
    with repository._connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM citation").fetchone()[0] == 0
