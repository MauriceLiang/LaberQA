"""Production retrieval that maps FAISS ids back to persisted successful chunks."""

from __future__ import annotations

from typing import Any

from app.core.config import Settings, settings
from app.repositories.document_repository import DocumentRepository
from app.services.embedding import EmbeddingService
from app.services.rerank import RerankService
from app.services.vector_store import (
    VectorStoreNotInitialized,
    VectorStoreService,
    VectorStoreSignatureMismatch,
)


class RetrievalService:
    def __init__(
        self,
        config: Settings = settings,
        *,
        repository: DocumentRepository | None = None,
        embedding_service: EmbeddingService | None = None,
        vector_store: VectorStoreService | None = None,
        rerank_service: RerankService | None = None,
    ) -> None:
        self.config = config
        self.repository = repository or DocumentRepository(config.database_path)
        self.embedding_service = embedding_service or EmbeddingService(config)
        self.vector_store = vector_store or VectorStoreService(
            config=config,
            embedding_service=self.embedding_service,
            index_dir=config.faiss_path / "production",
        )
        self.rerank_service = rerank_service or RerankService(config)

    def retrieve(self, query: str) -> list[dict[str, Any]]:
        status = self.vector_store.status
        if status == "not_initialized":
            raise VectorStoreNotInitialized("向量知识库尚未初始化")
        if status == "incompatible":
            raise VectorStoreSignatureMismatch("当前 Embedding 签名与生产索引不一致")
        query_vector = self.embedding_service.embed_query(query)
        hits = self.vector_store.search(query_vector, self.config.rag_top_k)
        chunks_by_id = {
            int(chunk["id"]): chunk for chunk in self.repository.list_success_chunks()
        }

        evidence: list[dict[str, Any]] = []
        seen: set[int] = set()
        for chunk_id, score in hits:
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            chunk = chunks_by_id.get(chunk_id)
            if chunk is None:
                continue
            retrieval_score = min(1.0, max(0.0, float(score)))
            evidence.append(
                {
                    "chunk_id": chunk_id,
                    "document_id": int(chunk["document_id"]),
                    "file_name": str(chunk["file_name"]),
                    "chunk_no": int(chunk["chunk_no"]),
                    "content": str(chunk["content"]),
                    "score": retrieval_score,
                    "retrieval_score": retrieval_score,
                    "rerank_score": None,
                    "rank_no": len(evidence) + 1,
                }
            )
        if self.config.rerank_enabled:
            return self.rerank_service.rerank(query, evidence)
        return evidence
