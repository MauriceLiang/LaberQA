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
from typing import Protocol

import faiss
import numpy as np

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


class VectorStoreService:
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
                return False
            self._index = loaded_index
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

    def add(self, chunks_with_vectors: Sequence[tuple[int, Sequence[float]]]) -> None:
        if not chunks_with_vectors:
            return
        with self._lock:
            ids = [int(chunk_id) for chunk_id, _ in chunks_with_vectors]
            if any(chunk_id <= 0 for chunk_id in ids) or len(set(ids)) != len(ids):
                raise ValueError("chunk ids must be unique positive integers")
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
            meta = self._new_meta(metadata_signature)
            self._persist(candidate, meta)
            self._index = candidate
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
            else:
                similarities, indices = self._index.search(vector, count)
            results: list[tuple[int, float]] = []
            for chunk_id, cosine in zip(indices[0], similarities[0], strict=True):
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
            self._meta = meta
            return True

    def _signature_for(self, dimension: int) -> EmbeddingSignature:
        if self.embedding_service is not None:
            return self.embedding_service.signature(dimension)
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
