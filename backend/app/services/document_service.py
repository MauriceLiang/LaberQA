"""Document upload and asynchronous knowledge-base import workflow."""

from __future__ import annotations

import logging
from threading import RLock
from typing import BinaryIO

from langchain_core.documents import Document

from app.core.config import Settings, settings
from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.rag.embeddings import LangChainEmbeddingService
from app.rag.errors import EmbeddingUnavailableError
from app.rag.loaders import LaborQADocumentLoader
from app.rag.splitters import LegalTextSplitter
from app.repositories.document_repository import DocumentRepository
from app.services.document_parser import ParserFactory, is_doc_parser_available
from app.services.file_storage import (
    DocumentConverterUnavailable,
    DocumentParseError,
    EmptyFileError,
    FileStorage,
    UploadValidationError,
)
from app.services.vector_store import VectorStoreError, VectorStoreService

logger = logging.getLogger(__name__)
_RESTART_ERROR = "服务重启导致任务中断"


class DocumentService:
    def __init__(
        self,
        config: Settings = settings,
        *,
        repository: DocumentRepository | None = None,
        file_storage: FileStorage | None = None,
        parser: type[ParserFactory] = ParserFactory,
        embedding_service: LangChainEmbeddingService | None = None,
        vector_store: VectorStoreService | None = None,
    ) -> None:
        self.config = config
        self.repository = repository or DocumentRepository(config.database_path)
        self.file_storage = file_storage or FileStorage(
            config.upload_path, max_size_bytes=config.max_upload_size_mb * 1024 * 1024
        )
        self.parser = parser
        self.embedding_service = embedding_service or LangChainEmbeddingService(config)
        self.vector_store = vector_store or VectorStoreService(
            config=config,
            embedding_service=self.embedding_service,
            index_dir=config.faiss_path / "production",
        )
        self.splitter = LegalTextSplitter(config.chunk_size, config.chunk_overlap)
        self._import_lock = RLock()

    def upload(
        self,
        source: BinaryIO,
        filename: str | None,
        content_type: str | None,
    ) -> dict:
        try:
            stored_file = self.file_storage.save(source, filename, content_type)
        except UploadValidationError as exc:
            raise AppError(exc.code, str(exc), exc.http_status) from exc

        if stored_file.file_type == "doc" and not is_doc_parser_available(self.config):
            self.file_storage.delete(stored_file.path)
            raise AppError(
                ErrorCode.DOC_CONVERTER_UNAVAILABLE,
                "DOC 解析器未安装或不可用",
                http_status=503,
            )

        try:
            return self.repository.create_document(
                file_name=stored_file.file_name,
                file_type=stored_file.file_type,
                file_path=str(stored_file.path),
                status="PROCESSING",
            )
        except Exception:
            self.file_storage.delete(stored_file.path)
            raise

    def reimport(self, document_id: int) -> dict:
        with self._import_lock:
            document = self.repository.get_document(document_id)
            if document is None:
                raise AppError(
                    ErrorCode.DOCUMENT_NOT_FOUND, "文档不存在", http_status=404
                )
            if document["status"] != "FAILED":
                raise AppError(
                    ErrorCode.INVALID_DOCUMENT_STATE,
                    "只有导入失败的文档可以重新导入",
                    http_status=409,
                )

            stale_ids = self.repository.delete_chunks(document_id)
            self._remove_vectors(stale_ids, "stale vectors before reimport")
            return self.repository.update_document(
                document_id,
                status="PROCESSING",
                error_message=None,
                chunk_count=0,
            )

    def delete_document(self, document_id: int) -> dict:
        """Delete a document and every persisted resource derived from it."""
        with self._import_lock:
            deleted = self.repository.delete_document(document_id)
            if deleted is None:
                raise AppError(
                    ErrorCode.DOCUMENT_NOT_FOUND, "文档不存在", http_status=404
                )

            document = deleted["document"]
            self._remove_vectors(
                deleted["chunk_ids"], "vectors after document deletion"
            )
            try:
                self.file_storage.delete(document["file_path"])
            except Exception:
                # The database is the source of truth. Keep the delete request
                # successful while making an orphaned file visible in logs.
                logger.exception(
                    "Could not remove source file for deleted document %s",
                    document_id,
                )
            return document

    def import_document(self, document_id: int) -> None:
        """Process a document in the FastAPI background-task worker."""
        with self._import_lock:
            document = self.repository.get_document(document_id)
            if document is None or document["status"] != "PROCESSING":
                return

            inserted_rows: list[dict] = []
            added_vector_ids: list[int] = []
            try:
                source_documents = self._load_documents(document)
                chunks = self.splitter.split_documents(source_documents)
                if not chunks:
                    raise EmptyFileError()

                vectors = self.embedding_service.embed_documents(
                    [chunk.page_content for chunk in chunks]
                )
                if len(vectors) != len(chunks):
                    raise EmbeddingUnavailableError("向量服务返回的结果数量不正确")

                inserted_rows = self.repository.insert_chunks(
                    document_id,
                    [
                        {
                            "chunk_no": int(chunk.metadata["chunk_no"]),
                            "content": chunk.page_content,
                        }
                        for chunk in chunks
                    ],
                )
                vector_documents = [
                    Document(
                        id=str(row["id"]),
                        page_content=chunk.page_content,
                        metadata={
                            "chunk_id": int(row["id"]),
                            "document_id": document_id,
                            "file_name": str(document["file_name"]),
                            "file_type": str(document["file_type"]),
                            "chunk_no": int(row["chunk_no"]),
                        },
                    )
                    for row, chunk in zip(inserted_rows, chunks, strict=True)
                ]
                added_ids = self.vector_store.add_documents(
                    vector_documents,
                    vectors=vectors,
                    ids=[str(row["id"]) for row in inserted_rows],
                )
                added_vector_ids = [int(chunk_id) for chunk_id in added_ids]

                updated = self.repository.update_document(
                    document_id,
                    status="SUCCESS",
                    error_message=None,
                    chunk_count=len(inserted_rows),
                )
                if updated is None:
                    raise RuntimeError("文档状态更新失败")
            except Exception as exc:
                self._rollback_import(document_id, inserted_rows, added_vector_ids)
                message = self._error_message(exc)
                try:
                    self.repository.update_document(
                        document_id,
                        status="FAILED",
                        error_message=message[:500],
                        chunk_count=0,
                    )
                except Exception:
                    logger.exception("Could not mark failed document %s", document_id)
                logger.exception("Document import failed for document %s", document_id)

    def _load_documents(self, document: dict) -> list[Document]:
        metadata = {
            "document_id": int(document["id"]),
            "file_name": str(document["file_name"]),
            "file_type": str(document["file_type"]),
        }
        if self.parser is ParserFactory:
            return LaborQADocumentLoader(
                document["file_path"],
                document["file_type"],
                config=self.config,
                metadata=metadata,
            ).load()

        source_text = self.parser.parse(document["file_path"], document["file_type"])
        return [
            Document(
                page_content=source_text,
                metadata={
                    "source": str(document["file_path"]),
                    "page": None,
                    **metadata,
                },
            )
        ]

    def recover_interrupted_imports(self) -> None:
        """Mark jobs interrupted by a process restart as failed and clean chunks."""
        stale_vector_ids: list[int] = []
        page = 1
        while True:
            documents, total = self.repository.list_documents(
                page=page, size=100, status="PROCESSING"
            )
            if not documents:
                break
            for document in documents:
                stale_vector_ids.extend(self.repository.delete_chunks(document["id"]))
                self.repository.update_document(
                    document["id"],
                    status="FAILED",
                    error_message=_RESTART_ERROR,
                    chunk_count=0,
                )
            if page * 100 >= total:
                break
            page += 1

        try:
            compatible = self.vector_store.load()
        except VectorStoreError:
            compatible = False
            logger.exception("Production vector index could not be loaded")
        if stale_vector_ids and compatible:
            try:
                self.vector_store.remove(stale_vector_ids)
            except Exception:
                logger.exception("Could not remove vectors from interrupted imports")
                self._rebuild_index()

    def _rollback_import(
        self,
        document_id: int,
        inserted_rows: list[dict],
        added_vector_ids: list[int],
    ) -> None:
        try:
            deleted_ids = self.repository.delete_chunks(document_id)
        except Exception:
            logger.exception("Could not remove chunks after import failure")
            deleted_ids = [row["id"] for row in inserted_rows]

        ids_to_remove = list(dict.fromkeys(added_vector_ids + deleted_ids))
        self._remove_vectors(ids_to_remove, "vectors after import failure")

    def _remove_vectors(self, chunk_ids: list[int], context: str) -> None:
        if not chunk_ids:
            return
        try:
            if not self.vector_store.is_signature_compatible():
                self.vector_store.load()
            if self.vector_store.is_signature_compatible():
                self.vector_store.remove(chunk_ids)
        except Exception:
            logger.exception("Could not remove %s", context)
            self._rebuild_index()

    def _rebuild_index(self) -> None:
        try:
            chunks = self.repository.list_success_chunks()
            if not chunks:
                self.vector_store.rebuild_from_success_chunks([])
                return
            vectors = self.embedding_service.embed_documents(
                [chunk["content"] for chunk in chunks]
            )
            if len(vectors) != len(chunks):
                raise EmbeddingUnavailableError("向量服务返回的结果数量不正确")
            self.vector_store.rebuild_from_success_chunks(
                [
                    (chunk["id"], vector)
                    for chunk, vector in zip(chunks, vectors, strict=True)
                ]
            )
        except Exception:
            logger.exception("Could not rebuild the production vector index")

    @staticmethod
    def _error_message(exc: Exception) -> str:
        if isinstance(exc, DocumentConverterUnavailable):
            return "DOC 解析器未安装或不可用"
        if isinstance(exc, DocumentParseError | EmptyFileError):
            return str(exc)
        if isinstance(exc, EmbeddingUnavailableError):
            return str(exc)
        return "文档导入失败"
