import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.dependencies import get_document_service
from app.core.config import Settings, settings
from app.core.database import initialize_database
from app.main import app
from app.rag.errors import EmbeddingUnavailableError
from app.repositories.document_repository import DocumentRepository
from app.schemas.contracts import EmbeddingSignature
from app.services.document_service import DocumentService
from app.services.file_storage import DocumentParseError, FileStorage
from app.services.vector_store import VectorStoreService


class _Parser:
    @staticmethod
    def parse(path: str, file_type: str) -> str:
        return "第一条 工资应当按时支付。\n第二条 劳动者依法享有休息权。"


class _FailingParser:
    @staticmethod
    def parse(path: str, file_type: str) -> str:
        raise DocumentParseError("TXT 文件不是有效的 UTF-8 文本")


class _EmbeddingService:
    provider = type(
        "Provider",
        (),
        {
            "name": "local",
            "model": "test-embedding",
            "normalize_embeddings": True,
            "dimension": 2,
        },
    )()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] if i % 2 == 0 else [0.0, 1.0] for i, _ in enumerate(texts)]

    def signature(self, embedding_dimension: int | None = None) -> EmbeddingSignature:
        return EmbeddingSignature(
            embedding_provider="local",
            embedding_model="test-embedding",
            embedding_dimension=embedding_dimension or 2,
            normalize_embeddings=True,
        )


class DocumentApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.original_values = {
            "database_url": settings.database_url,
            "upload_dir": settings.upload_dir,
            "faiss_dir": settings.faiss_dir,
        }
        settings.database_url = f"sqlite:///{self.root / 'test.db'}"
        settings.upload_dir = self.root / "uploads"
        settings.faiss_dir = self.root / "faiss"

    def tearDown(self) -> None:
        app.dependency_overrides.pop(get_document_service, None)
        for name, value in self.original_values.items():
            setattr(settings, name, value)
        self.directory.cleanup()

    def _service(self) -> DocumentService:
        config = Settings(
            database_url=settings.database_url,
            upload_dir=settings.upload_dir,
            faiss_dir=settings.faiss_dir,
            chunk_size=600,
            chunk_overlap=100,
        )
        embedding_service = _EmbeddingService()
        return DocumentService(
            config,
            repository=DocumentRepository(config.database_path),
            file_storage=FileStorage(config.upload_path),
            parser=_Parser,
            embedding_service=embedding_service,  # type: ignore[arg-type]
            vector_store=VectorStoreService(
                config,
                embedding_service=embedding_service,
                index_dir=config.faiss_path / "production",
            ),
        )

    def test_upload_import_detail_chunks_and_pagination(self) -> None:
        with TestClient(app) as client:
            app.state.document_service = self._service()
            response = client.post(
                "/api/documents/upload",
                files={"file": ("../劳动法.txt", "上传内容".encode(), "text/plain")},
            )
            self.assertEqual(response.status_code, 202)
            accepted = response.json()["data"]
            self.assertEqual(accepted["status"], "PROCESSING")
            document_id = accepted["document_id"]

            detail_response = client.get(f"/api/documents/{document_id}")
            self.assertEqual(detail_response.status_code, 200)
            self.assertEqual(detail_response.json()["data"]["status"], "SUCCESS")
            self.assertEqual(detail_response.json()["data"]["chunk_count"], 2)

            chunks_response = client.get(
                f"/api/documents/{document_id}/chunks?page=1&size=1"
            )
            self.assertEqual(chunks_response.status_code, 200)
            chunk_page = chunks_response.json()["data"]
            self.assertEqual(chunk_page["total"], 2)
            self.assertEqual(chunk_page["items"][0]["vector_key"], "chunk:1")

            list_response = client.get(
                "/api/documents?keyword=%E5%8A%B3%E5%8A%A8%E6%B3%95"
            )
            self.assertEqual(list_response.status_code, 200)
            self.assertEqual(list_response.json()["data"]["total"], 1)

            search_results = app.state.document_service.vector_store.search(
                [1.0, 0.0], 5
            )
            self.assertEqual(search_results, [(1, 1.0), (2, 0.5)])

    def test_upload_rejects_mime_mismatch_and_empty_file(self) -> None:
        with TestClient(app) as client:
            app.state.document_service = self._service()
            bad_mime = client.post(
                "/api/documents/upload",
                files={"file": ("law.txt", b"text", "application/pdf")},
            )
            empty = client.post(
                "/api/documents/upload",
                files={"file": ("law.txt", b"", "text/plain")},
            )

        self.assertEqual(bad_mime.status_code, 400)
        self.assertEqual(bad_mime.json()["code"], 40003)
        self.assertEqual(empty.status_code, 400)
        self.assertEqual(empty.json()["code"], 40002)

    def test_doc_upload_requires_configured_converter_before_acceptance(self) -> None:
        with (
            patch(
                "app.services.document_service.is_doc_parser_available",
                return_value=False,
            ),
            TestClient(app) as client,
        ):
            service = self._service()
            app.state.document_service = service
            response = client.post(
                "/api/documents/upload",
                files={"file": ("law.doc", b"legacy document", "application/msword")},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], 50304)
        self.assertEqual(list(service.config.upload_path.iterdir()), [])

    def test_failed_vector_write_rolls_back_chunks_and_marks_document_failed(
        self,
    ) -> None:
        with TestClient(app) as client:
            service = self._service()
            app.state.document_service = service
            with patch.object(
                service.vector_store, "add_documents", side_effect=OSError
            ):
                response = client.post(
                    "/api/documents/upload",
                    files={"file": ("law.txt", b"legal text", "text/plain")},
                )

            self.assertEqual(response.status_code, 202)
            document_id = response.json()["data"]["document_id"]
            document = service.repository.get_document(document_id)
            chunks, chunk_total = service.repository.list_chunks(document_id)
            self.assertEqual(document["status"], "FAILED")
            self.assertEqual(document["chunk_count"], 0)
            self.assertEqual(document["error_message"], "文档导入失败")
            self.assertEqual(chunks, [])
            self.assertEqual(chunk_total, 0)
            self.assertFalse(service.vector_store.index_path.exists())

    def test_parser_and_embedding_failures_mark_document_failed_without_chunks(
        self,
    ) -> None:
        with TestClient(app) as client:
            parser_service = self._service()
            parser_service.parser = _FailingParser
            app.state.document_service = parser_service
            parser_response = client.post(
                "/api/documents/upload",
                files={"file": ("parse-error.txt", b"legal text", "text/plain")},
            )

            embedding_service = self._service()
            app.state.document_service = embedding_service
            with patch.object(
                embedding_service.embedding_service,
                "embed_documents",
                side_effect=EmbeddingUnavailableError("测试 Embedding 失败"),
            ):
                embedding_response = client.post(
                    "/api/documents/upload",
                    files={
                        "file": ("embedding-error.txt", b"legal text", "text/plain")
                    },
                )

        self.assertEqual(parser_response.status_code, 202)
        self.assertEqual(embedding_response.status_code, 202)
        for response, expected_message in (
            (parser_response, "TXT 文件不是有效的 UTF-8 文本"),
            (embedding_response, "测试 Embedding 失败"),
        ):
            document_id = response.json()["data"]["document_id"]
            document = embedding_service.repository.get_document(document_id)
            chunks, total = embedding_service.repository.list_chunks(document_id)
            self.assertEqual(document["status"], "FAILED")
            self.assertEqual(document["error_message"], expected_message)
            self.assertEqual(chunks, [])
            self.assertEqual(total, 0)

    def test_failed_document_can_be_reimported_once(self) -> None:
        with TestClient(app) as client:
            service = self._service()
            app.state.document_service = service
            document = service.repository.create_document(
                file_name="law.txt",
                file_type="txt",
                file_path="missing.txt",
                status="FAILED",
            )
            first = client.post(f"/api/documents/{document['id']}/reimport")
            second = client.post(f"/api/documents/{document['id']}/reimport")

        self.assertEqual(first.status_code, 202)
        self.assertEqual(first.json()["data"]["status"], "PROCESSING")
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["code"], 40901)

    def test_delete_document_removes_all_derived_data_and_source_file(self) -> None:
        with TestClient(app) as client:
            service = self._service()
            app.state.document_service = service
            response = client.post(
                "/api/documents/upload",
                files={"file": ("law.txt", b"legal text", "text/plain")},
            )
            document_id = response.json()["data"]["document_id"]
            document = service.repository.get_document(document_id)
            chunks, total = service.repository.list_chunks(document_id)
            self.assertEqual(total, 2)
            source_path = Path(document["file_path"])
            self.assertTrue(source_path.exists())

            session_id = str(uuid4())
            with service.repository._connection() as connection:
                connection.execute(
                    "INSERT INTO session (id, title) VALUES (?, ?)",
                    (session_id, "引用测试"),
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

            delete_response = client.delete(f"/api/documents/{document_id}")
            self.assertEqual(delete_response.status_code, 200)
            self.assertEqual(
                delete_response.json(),
                {"code": 0, "message": "deleted", "data": None},
            )
            self.assertIsNone(service.repository.get_document(document_id))
            self.assertEqual(service.repository.list_chunks(document_id), ([], 0))
            self.assertFalse(source_path.exists())
            with service.repository._connection() as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM citation").fetchone()[0],
                    0,
                )
            self.assertFalse(service.vector_store.is_ready)

    def test_delete_missing_document_returns_not_found(self) -> None:
        with TestClient(app) as client:
            app.state.document_service = self._service()
            response = client.delete("/api/documents/999")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], 40401)

    def test_missing_document_returns_not_found_for_detail_and_chunks(self) -> None:
        with TestClient(app) as client:
            app.state.document_service = self._service()
            detail = client.get("/api/documents/999")
            chunks = client.get("/api/documents/999/chunks")

        self.assertEqual(detail.status_code, 404)
        self.assertEqual(detail.json()["code"], 40401)
        self.assertEqual(chunks.status_code, 404)
        self.assertEqual(chunks.json()["code"], 40401)

    def test_startup_marks_interrupted_imports_failed(self) -> None:
        initialize_database()
        repository = DocumentRepository(settings.database_path)
        document = repository.create_document(
            file_name="interrupted.txt",
            file_type="txt",
            file_path=str(self.root / "interrupted.txt"),
            status="PROCESSING",
        )
        repository.insert_chunks(
            document["id"], [{"chunk_no": 1, "content": "temporary chunk"}]
        )

        with TestClient(app):
            recovered = repository.get_document(document["id"])
            chunks, count = repository.list_chunks(document["id"])

        self.assertEqual(recovered["status"], "FAILED")
        self.assertEqual(recovered["error_message"], "服务重启导致任务中断")
        self.assertEqual(recovered["chunk_count"], 0)
        self.assertEqual(chunks, [])
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
