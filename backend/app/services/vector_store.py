import json
import logging
import os
import shutil
import sys
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any, Protocol

import faiss
import numpy as np
from langchain_community.docstore.in_memory import InMemoryDocstore
from langchain_community.vectorstores import FAISS as LangChainFAISS
from langchain_community.vectorstores.utils import DistanceStrategy
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore

from app.core.config import Settings, settings
from app.rag.constants import (
    COMPATIBLE_SPLITTER_VERSIONS,
    CURRENT_SPLITTER_VERSION,
)
from app.schemas.contracts import EmbeddingSignature, IndexMeta

logger = logging.getLogger(__name__)

_PROCESS_LOCK = RLock()


class EmbeddingSignatureProvider(Protocol):
    def signature(self, dimension: int | None = None) -> EmbeddingSignature: ...


class VectorStoreError(RuntimeError):
    """Base exception for persisted vector index errors."""


class VectorStoreNotInitialized(VectorStoreError):
    """Raised when a search is requested before an index is ready."""


class VectorStoreSignatureMismatch(VectorStoreError):
    """Raised when persisted vectors were created with another signature."""

    def __init__(self, message: str, meta: IndexMeta | None = None) -> None:
        super().__init__(message)
        self.meta = meta


class VectorStorePersistenceError(VectorStoreError):
    """Raised when the index and its metadata cannot be read or written."""


class _UnavailableEmbeddings(Embeddings):
    """Placeholder used when a store is only used with precomputed vectors."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        del texts
        raise ValueError("该向量库未配置文本 Embeddings")

    def embed_query(self, text: str) -> list[float]:
        del text
        raise ValueError("该向量库未配置查询 Embeddings")


class VectorStoreService(VectorStore):
    """Persisted LangChain FAISS store with LaberQA's business compatibility.

    SQLite remains the source of truth for chunk content.  The LangChain
    ``FAISS`` instance therefore keeps a small in-memory Document projection
    containing the stable ``chunk_id`` metadata, while this service continues
    to own signature checks, atomic persistence, and lifecycle operations.
    """

    def __init__(
        self,
        config: Settings = settings,
        embedding_service: EmbeddingSignatureProvider | None = None,
        index_dir: Path | None = None,
    ) -> None:
        self.config = config
        self.embedding_service = embedding_service
        self.index_dir = index_dir or config.faiss_path / "production"
        self.index_path = self.index_dir / "index.faiss"
        self.meta_path = self.index_dir / "index_meta.json"
        self._index: faiss.IndexIDMap2 | None = None
        self._langchain_store: LangChainFAISS | None = None
        self._documents: dict[int, Document] = {}
        self._meta: IndexMeta | None = None
        self._lock = _PROCESS_LOCK

    @property
    def meta(self) -> IndexMeta | None:
        with self._lock:
            return self._meta

    @property
    def status(self) -> str:
        with self._lock:
            if self._meta is not None and not self.is_signature_compatible():
                return "incompatible"
            return (
                "ready"
                if self._index is not None and self._index.ntotal > 0
                else "not_initialized"
            )

    @property
    def is_ready(self) -> bool:
        return self.status == "ready"

    def load(self) -> bool:
        """Load the persisted index, returning False when it is not initialized."""
        with self._lock:
            index_exists = self.index_path.is_file()
            meta_exists = self.meta_path.is_file()
            self._index = None
            self._langchain_store = None
            self._documents = {}
            self._meta = None
            if not index_exists and not meta_exists:
                return False
            if index_exists != meta_exists:
                raise VectorStorePersistenceError(
                    "向量索引文件与元数据不完整，需重建索引"
                )

            try:
                payload = json.loads(self.meta_path.read_text(encoding="utf-8"))
                meta = IndexMeta.model_validate(payload)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                raise VectorStorePersistenceError("向量索引元数据无效") from exc

            self._meta = meta
            if not self.is_signature_compatible():
                raise VectorStoreSignatureMismatch(
                    "当前 Embedding 签名与生产索引不一致", meta
                )

            try:
                loaded_index = faiss.read_index(str(self.index_path))
                if not isinstance(loaded_index, faiss.IndexIDMap2):
                    loaded_index = faiss.downcast_index(loaded_index)
                if not isinstance(loaded_index, faiss.IndexIDMap2):
                    raise TypeError("FAISS index does not preserve external ids")
                if loaded_index.d != meta.embedding_dimension:
                    raise ValueError("FAISS dimension does not match index metadata")
                if loaded_index.metric_type != faiss.METRIC_INNER_PRODUCT:
                    raise ValueError("FAISS index metric is not inner product")
                ids = faiss.vector_to_array(loaded_index.id_map)
                if len(ids) != loaded_index.ntotal or len(set(ids.tolist())) != len(
                    ids
                ):
                    raise ValueError("FAISS id mapping is invalid")
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                raise VectorStorePersistenceError("FAISS 向量索引无效") from exc

            if loaded_index.ntotal == 0:
                self._meta = meta
                return False
            self._index = loaded_index
            self._documents = {
                chunk_id: self._document_for_chunk_id(chunk_id)
                for chunk_id in self._index_ids(loaded_index)
            }
            self._langchain_store = self._build_langchain_store(
                loaded_index, self._documents
            )
            return True

    def is_signature_compatible(
        self, signature: EmbeddingSignature | None = None
    ) -> bool:
        with self._lock:
            if self._meta is None:
                return False
            expected = signature or self._signature_for(self._meta.embedding_dimension)
            return self._same_embedding_signature(self._meta, expected) and (
                self._meta.chunk_size == self.config.chunk_size
                and self._meta.chunk_overlap == self.config.chunk_overlap
                and self._meta.splitter_version in COMPATIBLE_SPLITTER_VERSIONS
            )

    def add(
        self,
        chunks_with_vectors: Sequence[tuple[int, Sequence[float]]],
        *,
        documents: Sequence[Document] | None = None,
    ) -> None:
        """Add precomputed vectors while keeping the legacy service API."""
        self._add_with_documents(chunks_with_vectors, documents)

    def add_documents(self, documents: list[Document], **kwargs: Any) -> list[str]:
        """Add LangChain Documents with caller-supplied or computed vectors."""
        if not documents:
            return []
        vectors = kwargs.pop("vectors", None)
        if vectors is None:
            if self.embedding_service is None or not hasattr(
                self.embedding_service, "embed_documents"
            ):
                raise ValueError("该向量库未配置文本 Embeddings")
            vectors = self.embedding_service.embed_documents(
                [document.page_content for document in documents]
            )
        if len(vectors) != len(documents):
            raise ValueError("文档数量与向量数量不一致")
        ids = kwargs.pop("ids", None)
        if ids is not None and len(ids) != len(documents):
            raise ValueError("文档数量与 ids 数量不一致")
        if kwargs:
            unexpected = ", ".join(sorted(kwargs))
            raise TypeError(f"不支持的向量库参数: {unexpected}")
        next_id = max(self._documents, default=0) + 1
        chunk_ids: list[int] = []
        for index, document in enumerate(documents):
            explicit_id = ids[index] if ids is not None else None
            chunk_id = self._document_chunk_id(document, explicit_id, next_id)
            if explicit_id is None and not document.metadata.get("chunk_id"):
                next_id = chunk_id + 1
            chunk_ids.append(chunk_id)
        self._add_with_documents(list(zip(chunk_ids, vectors, strict=True)), documents)
        return [str(chunk_id) for chunk_id in chunk_ids]

    def add_texts(
        self,
        texts: Sequence[str],
        metadatas: list[dict[str, Any]] | None = None,
        *,
        ids: list[str] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        """Implement the LangChain VectorStore text insertion contract."""
        if kwargs:
            unexpected = ", ".join(sorted(kwargs))
            raise TypeError(f"不支持的向量库参数: {unexpected}")
        if self.embedding_service is None or not hasattr(
            self.embedding_service, "embed_documents"
        ):
            raise ValueError("该向量库未配置文本 Embeddings")
        values = list(texts)
        metadata_values = metadatas or [{} for _ in values]
        if len(metadata_values) != len(values):
            raise ValueError("文本数量与 metadata 数量不一致")
        documents = [
            Document(page_content=text, metadata=dict(metadata))
            for text, metadata in zip(values, metadata_values, strict=True)
        ]
        return self.add_documents(documents, ids=ids)

    @classmethod
    def from_texts(
        cls,
        texts: list[str],
        embedding: Embeddings,
        metadatas: list[dict[str, Any]] | None = None,
        *,
        ids: list[str] | None = None,
        **kwargs: Any,
    ) -> "VectorStoreService":
        """Create a persisted store through the standard LangChain factory."""
        config = kwargs.pop("config", settings)
        index_dir = kwargs.pop("index_dir", None)
        if kwargs:
            unexpected = ", ".join(sorted(kwargs))
            raise TypeError(f"不支持的向量库参数: {unexpected}")
        if ids is not None and len(ids) != len(texts):
            raise ValueError("文本数量与 ids 数量不一致")
        metadata_values = metadatas or [{} for _ in texts]
        if len(metadata_values) != len(texts):
            raise ValueError("文本数量与 metadata 数量不一致")
        documents = [
            Document(
                id=(ids[index] if ids is not None else str(index + 1)),
                page_content=text,
                metadata=dict(metadata_values[index]),
            )
            for index, text in enumerate(texts)
        ]
        vectors = embedding.embed_documents(texts)
        store = cls(
            config=config,
            embedding_service=embedding,
            index_dir=index_dir,
        )
        store.add_documents(documents, vectors=vectors, ids=ids)
        return store

    def similarity_search(
        self, query: str, k: int = 4, **kwargs: Any
    ) -> list[Document]:
        return [
            document
            for document, _ in self.similarity_search_with_score(query, k=k, **kwargs)
        ]

    def similarity_search_with_score(
        self, query: str, k: int = 4, **kwargs: Any
    ) -> list[tuple[Document, float]]:
        if self.embedding_service is None or not hasattr(
            self.embedding_service, "embed_query"
        ):
            raise ValueError("该向量库未配置查询 Embeddings")
        return self.similarity_search_with_score_by_vector(
            self.embedding_service.embed_query(query), k=k, **kwargs
        )

    def similarity_search_by_vector(
        self, embedding: list[float], k: int = 4, **kwargs: Any
    ) -> list[Document]:
        return [
            document
            for document, _ in self.similarity_search_with_score_by_vector(
                embedding, k=k, **kwargs
            )
        ]

    def similarity_search_with_score_by_vector(
        self, embedding: list[float], k: int = 4, **kwargs: Any
    ) -> list[tuple[Document, float]]:
        if k < 1:
            return []
        score_threshold = kwargs.pop("score_threshold", None)
        filter_value = kwargs.pop("filter", None)
        fetch_k = int(kwargs.pop("fetch_k", k))
        if kwargs:
            unexpected = ", ".join(sorted(kwargs))
            raise TypeError(f"不支持的向量库参数: {unexpected}")
        hits = self.search(embedding, max(k, fetch_k))
        results = [
            (self._documents[chunk_id], score)
            for chunk_id, score in hits
            if chunk_id in self._documents
        ]
        if filter_value is not None:
            if callable(filter_value):
                results = [
                    (document, score)
                    for document, score in results
                    if filter_value(document.metadata)
                ]
            elif isinstance(filter_value, dict):
                results = [
                    (document, score)
                    for document, score in results
                    if all(
                        document.metadata.get(key) == value
                        for key, value in filter_value.items()
                    )
                ]
            else:
                raise TypeError("filter 必须是字典或可调用对象")
        if score_threshold is not None:
            results = [
                (document, score)
                for document, score in results
                if score >= float(score_threshold)
            ]
        return results[:k]

    @staticmethod
    def _index_ids(index: faiss.IndexIDMap2) -> list[int]:
        ids = faiss.vector_to_array(index.id_map).astype(np.int64, copy=False)
        return [int(chunk_id) for chunk_id in ids.tolist()]

    @staticmethod
    def _document_for_chunk_id(chunk_id: int) -> Document:
        return Document(
            id=str(chunk_id),
            page_content="",
            metadata={"chunk_id": chunk_id},
        )

    @staticmethod
    def _normalize_document(document: Document, chunk_id: int) -> Document:
        metadata = dict(document.metadata)
        metadata["chunk_id"] = chunk_id
        return Document(
            id=str(chunk_id),
            page_content=document.page_content,
            metadata=metadata,
        )

    @staticmethod
    def _document_chunk_id(
        document: Document, explicit_id: str | None, fallback: int | None = None
    ) -> int:
        value: Any = explicit_id
        if value is None:
            value = document.metadata.get("chunk_id", document.id)
        if value is None and fallback is not None:
            value = fallback
        try:
            chunk_id = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("LangChain Document 必须包含正整数 chunk_id") from exc
        if chunk_id <= 0:
            raise ValueError("chunk_id 必须是正整数")
        return chunk_id

    def _build_langchain_store(
        self,
        index: faiss.IndexIDMap2,
        documents: dict[int, Document],
    ) -> LangChainFAISS:
        document_store = InMemoryDocstore(
            {str(chunk_id): document for chunk_id, document in documents.items()}
        )
        index_to_docstore_id = {
            chunk_id: str(chunk_id) for chunk_id in self._index_ids(index)
        }
        embedding_function = (
            self.embedding_service
            if isinstance(self.embedding_service, Embeddings)
            else _UnavailableEmbeddings()
        )
        return LangChainFAISS(
            embedding_function=embedding_function,
            index=index,
            docstore=document_store,
            index_to_docstore_id=index_to_docstore_id,
            normalize_L2=False,
            distance_strategy=DistanceStrategy.MAX_INNER_PRODUCT,
        )

    def _add_with_documents(
        self,
        chunks_with_vectors: Sequence[tuple[int, Sequence[float]]],
        documents: Sequence[Document] | None = None,
    ) -> None:
        if not chunks_with_vectors:
            return
        with self._lock:
            ids = [int(chunk_id) for chunk_id, _ in chunks_with_vectors]
            if any(chunk_id <= 0 for chunk_id in ids) or len(set(ids)) != len(ids):
                raise ValueError("chunk ids must be unique positive integers")
            if documents is not None and len(documents) != len(ids):
                raise ValueError("文档数量与向量数量不一致")
            vectors = self._matrix([vector for _, vector in chunks_with_vectors])
            dimension = int(vectors.shape[1])
            if self._index is not None:
                if self._meta is None:
                    raise VectorStorePersistenceError("向量索引缺少元数据")
                if dimension != self._meta.embedding_dimension:
                    raise VectorStoreSignatureMismatch(
                        "Embedding 向量维度与生产索引不一致", self._meta
                    )
                if not self.is_signature_compatible():
                    raise VectorStoreSignatureMismatch(
                        "当前 Embedding 签名与生产索引不一致", self._meta
                    )
                candidate = faiss.clone_index(self._index)
                existing_ids = set(
                    faiss.vector_to_array(candidate.id_map).astype(np.int64).tolist()
                )
                if existing_ids.intersection(ids):
                    raise ValueError("one or more chunk ids already exist in FAISS")
                metadata_signature = self._signature_for(dimension)
            else:
                if self._meta is not None:
                    if not self.is_signature_compatible():
                        raise VectorStoreSignatureMismatch(
                            "当前 Embedding 签名与生产索引不一致", self._meta
                        )
                    if self._meta.embedding_dimension != dimension:
                        raise VectorStoreSignatureMismatch(
                            "Embedding 向量维度与生产索引不一致", self._meta
                        )
                metadata_signature = self._signature_for(dimension)
                candidate = faiss.IndexIDMap2(faiss.IndexFlatIP(dimension))

            candidate.add_with_ids(vectors, np.asarray(ids, dtype=np.int64))
            projected_documents = dict(self._documents)
            for index, chunk_id in enumerate(ids):
                projected_documents[chunk_id] = (
                    self._normalize_document(documents[index], chunk_id)
                    if documents is not None
                    else self._document_for_chunk_id(chunk_id)
                )
            meta = self._new_meta(metadata_signature)
            self._persist(candidate, meta)
            self._index = candidate
            self._documents = projected_documents
            self._langchain_store = self._build_langchain_store(
                candidate, projected_documents
            )
            self._meta = meta

    def remove(self, chunk_ids: Sequence[int]) -> None:
        ids = sorted({int(chunk_id) for chunk_id in chunk_ids})
        if not ids:
            return
        with self._lock:
            if self._index is None or self._meta is None:
                return
            if not self.is_signature_compatible():
                raise VectorStoreSignatureMismatch(
                    "当前 Embedding 签名与生产索引不一致", self._meta
                )
            candidate = faiss.clone_index(self._index)
            existing_ids = set(faiss.vector_to_array(candidate.id_map).tolist())
            selected = [chunk_id for chunk_id in ids if chunk_id in existing_ids]
            if not selected:
                return
            candidate.remove_ids(np.asarray(selected, dtype=np.int64))
            meta = self._new_meta(self._signature_for(self._meta.embedding_dimension))
            self._persist(candidate, meta)
            self._index = candidate
            self._documents = {
                chunk_id: document
                for chunk_id, document in self._documents.items()
                if chunk_id not in selected
            }
            self._langchain_store = self._build_langchain_store(
                candidate, self._documents
            )
            self._meta = meta

    def search(
        self, query_vector: Sequence[float], top_k: int
    ) -> list[tuple[int, float]]:
        if top_k < 1:
            return []
        with self._lock:
            if self._index is None or self._meta is None or self._index.ntotal == 0:
                raise VectorStoreNotInitialized("向量知识库尚未初始化")
            if not self.is_signature_compatible():
                raise VectorStoreSignatureMismatch(
                    "当前 Embedding 签名与生产索引不一致", self._meta
                )
            vector = self._matrix([query_vector])
            if vector.shape[1] != self._meta.embedding_dimension:
                raise VectorStoreSignatureMismatch(
                    "查询向量维度与生产索引不一致", self._meta
                )
            count = min(top_k, self._index.ntotal)
            if count == 0:
                return []
            if sys.platform == "darwin":
                similarities, indices = self._search_without_openmp(
                    self._index, vector, count
                )
                scored_ids = zip(indices[0], similarities[0], strict=True)
            else:
                if self._langchain_store is None:
                    self._langchain_store = self._build_langchain_store(
                        self._index, self._documents
                    )
                documents_with_scores = (
                    self._langchain_store.similarity_search_with_score_by_vector(
                        vector[0].tolist(), count
                    )
                )
                scored_ids = (
                    (
                        int(document.metadata["chunk_id"]),
                        score,
                    )
                    for document, score in documents_with_scores
                )
            results: list[tuple[int, float]] = []
            for chunk_id, cosine in scored_ids:
                if chunk_id < 0:
                    continue
                retrieval_score = min(1.0, max(0.0, (float(cosine) + 1.0) / 2.0))
                results.append((int(chunk_id), retrieval_score))
            return results

    @staticmethod
    def _search_without_openmp(
        index: faiss.IndexIDMap2, query: np.ndarray, count: int
    ) -> tuple[np.ndarray, np.ndarray]:
        """Search small macOS indexes without crossing competing OpenMP runtimes."""
        vectors = np.asarray(
            index.index.reconstruct_n(0, index.ntotal), dtype=np.float32
        )
        ids = faiss.vector_to_array(index.id_map).astype(np.int64, copy=False)
        scores = vectors @ query[0]
        order = np.argsort(-scores, kind="stable")[:count]
        return scores[order][None, :], ids[order][None, :]

    def save(self) -> None:
        with self._lock:
            if self._index is None or self._meta is None:
                raise VectorStoreNotInitialized("向量知识库尚未初始化")
            self._persist(self._index, self._meta)

    def rebuild_from_success_chunks(
        self,
        chunks_with_vectors: Sequence[tuple[int, Sequence[float]]],
        signature: EmbeddingSignature | None = None,
    ) -> bool:
        """Replace the index with embeddings from all successful document chunks."""
        with self._lock:
            if not chunks_with_vectors:
                for path in (self.index_path, self.meta_path):
                    try:
                        path.unlink(missing_ok=True)
                    except OSError as exc:
                        raise VectorStorePersistenceError("清理旧向量索引失败") from exc
                self._index = None
                self._langchain_store = None
                self._documents = {}
                self._meta = None
                return False

            ids = [int(chunk_id) for chunk_id, _ in chunks_with_vectors]
            if any(chunk_id <= 0 for chunk_id in ids) or len(set(ids)) != len(ids):
                raise ValueError("chunk ids must be unique positive integers")
            vectors = self._matrix([vector for _, vector in chunks_with_vectors])
            dimension = int(vectors.shape[1])
            selected_signature = signature or self._signature_for(dimension)
            if selected_signature.embedding_dimension != dimension:
                raise VectorStoreSignatureMismatch(
                    "重建向量维度与 Embedding 签名不一致", self._meta
                )
            if not self._same_embedding_signature(
                selected_signature,
                self._signature_for(dimension),
            ):
                raise VectorStoreSignatureMismatch(
                    "重建签名与当前 Embedding Provider 不一致"
                )

            candidate = faiss.IndexIDMap2(faiss.IndexFlatIP(dimension))
            candidate.add_with_ids(vectors, np.asarray(ids, dtype=np.int64))
            meta = self._new_meta(selected_signature)
            self._persist(candidate, meta)
            self._index = candidate
            self._documents = {
                chunk_id: self._document_for_chunk_id(chunk_id) for chunk_id in ids
            }
            self._langchain_store = self._build_langchain_store(
                candidate, self._documents
            )
            self._meta = meta
            return True

    def _signature_for(self, dimension: int) -> EmbeddingSignature:
        signature = getattr(self.embedding_service, "signature", None)
        if signature is not None:
            return signature(dimension)
        return EmbeddingSignature(
            embedding_provider=self.config.embedding_provider,
            embedding_model=self.config.embedding_model,
            embedding_dimension=dimension,
            normalize_embeddings=self.config.embedding_normalize,
        )

    def _new_meta(self, signature: EmbeddingSignature) -> IndexMeta:
        return IndexMeta(
            **signature.model_dump(),
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
            splitter_version=CURRENT_SPLITTER_VERSION,
            created_at=datetime.now(UTC),
        )

    @staticmethod
    def _same_embedding_signature(
        actual: EmbeddingSignature, expected: EmbeddingSignature
    ) -> bool:
        return (
            actual.embedding_provider == expected.embedding_provider
            and actual.embedding_model == expected.embedding_model
            and actual.embedding_dimension == expected.embedding_dimension
            and actual.normalize_embeddings == expected.normalize_embeddings
        )

    @staticmethod
    def _matrix(vectors: Sequence[Sequence[float]]) -> np.ndarray:
        if not vectors:
            raise ValueError("at least one embedding vector is required")
        matrix = np.asarray(vectors, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[1] == 0:
            raise ValueError(
                "embedding vectors must have a consistent positive dimension"
            )
        if not np.isfinite(matrix).all():
            raise ValueError("embedding vectors must contain finite values")
        norms = np.linalg.norm(matrix, axis=1)
        if np.any(norms == 0):
            raise ValueError("embedding vectors cannot be zero vectors")
        matrix = matrix / norms[:, None]
        return np.ascontiguousarray(matrix, dtype=np.float32)

    def _persist(self, index: faiss.IndexIDMap2, meta: IndexMeta) -> None:
        temporary_paths: list[Path] = []
        try:
            self.index_dir.mkdir(parents=True, exist_ok=True)
            index_fd, index_temp_name = tempfile.mkstemp(
                prefix=".index-", suffix=".faiss.tmp", dir=self.index_dir
            )
            os.close(index_fd)
            index_temp = Path(index_temp_name)
            temporary_paths.append(index_temp)
            faiss.write_index(index, str(index_temp))

            meta_fd, meta_temp_name = tempfile.mkstemp(
                prefix=".index-meta-", suffix=".json.tmp", dir=self.index_dir
            )
            meta_temp = Path(meta_temp_name)
            temporary_paths.append(meta_temp)
            with os.fdopen(meta_fd, "w", encoding="utf-8") as file:
                json.dump(
                    meta.model_dump(mode="json"), file, ensure_ascii=False, indent=2
                )
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())

            backups: dict[Path, Path | None] = {}
            for target in (self.index_path, self.meta_path):
                if not target.exists():
                    backups[target] = None
                    continue
                backup_fd, backup_name = tempfile.mkstemp(
                    prefix=f".{target.name}-backup-", dir=self.index_dir
                )
                os.close(backup_fd)
                backup_path = Path(backup_name)
                temporary_paths.append(backup_path)
                backup_path.unlink()
                try:
                    os.link(target, backup_path)
                except OSError:
                    shutil.copy2(target, backup_path)
                backups[target] = backup_path

            try:
                # Each completed file is installed with a same-filesystem atomic rename.
                os.replace(index_temp, self.index_path)
                os.replace(meta_temp, self.meta_path)
            except OSError:
                for target, backup in backups.items():
                    if backup is None:
                        target.unlink(missing_ok=True)
                    elif backup.exists():
                        os.replace(backup, target)
                raise
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            logger.exception("Unable to persist FAISS index")
            raise VectorStorePersistenceError("保存向量索引失败") from exc
        finally:
            for path in temporary_paths:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Unable to remove temporary vector index file")


class KnowledgeVectorStore(VectorStoreService):
    """Named LangChain-facing alias for the persisted knowledge store."""
