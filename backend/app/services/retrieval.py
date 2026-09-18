"""Domain retrieval pipeline built on the LangChain VectorStore retriever."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from typing import Any

from langchain_core.documents import Document
from langchain_core.runnables import Runnable, RunnableLambda, RunnablePassthrough

from app.core.config import Settings, settings
from app.rag.embeddings import LangChainEmbeddingService
from app.repositories.document_repository import DocumentRepository
from app.services.rerank import RerankService
from app.services.vector_store import (
    VectorStoreNotInitialized,
    VectorStoreService,
    VectorStoreSignatureMismatch,
)


class DomainRetrievalService:
    """Apply LaborQA's SQLite mapping and reranking around a LangChain retriever.

    The vector store owns embedding and FAISS retrieval. This service keeps the
    business boundary: SQLite remains authoritative for chunk content and
    source metadata, while optional domain reranking produces final evidence.
    ``retriever`` is a LangChain Runnable pipeline so callers do not need a
    custom retriever adapter.
    """

    def __init__(
        self,
        config: Settings = settings,
        *,
        repository: DocumentRepository | None = None,
        embedding_service: LangChainEmbeddingService | None = None,
        vector_store: VectorStoreService | None = None,
        rerank_service: RerankService | None = None,
    ) -> None:
        self.config = config
        self.repository = repository or DocumentRepository(config.database_path)
        self.embedding_service = embedding_service or LangChainEmbeddingService(config)
        self.vector_store = vector_store or VectorStoreService(
            config=config,
            embedding_service=self.embedding_service,
            index_dir=config.faiss_path / "production",
        )
        if (
            callable(getattr(self.vector_store, "as_retriever", None))
            and getattr(self.vector_store, "embedding_service", None) is None
        ):
            # Keep injected VectorStore implementations compatible with the
            # production Embeddings facade without changing their public API.
            self.vector_store.embedding_service = self.embedding_service
        self.rerank_service = rerank_service or RerankService(config)
        self.candidate_retriever = self._build_candidate_retriever()
        self.retriever = self._build_domain_retriever()

    def _build_candidate_retriever(self) -> Any | None:
        as_retriever = getattr(self.vector_store, "as_retriever", None)
        if not callable(as_retriever):
            return None
        return as_retriever(search_kwargs={"k": self.config.rag_top_k})

    def _build_domain_retriever(self) -> Runnable[Any, list[Document]] | None:
        if self.candidate_retriever is None:
            return None
        return {
            "query": RunnablePassthrough(),
            "documents": self.candidate_retriever,
        } | RunnableLambda(self._documents_to_evidence_documents)

    def retrieve(self, query: str) -> list[dict[str, Any]]:
        """Synchronously retrieve evidence for legacy service callers."""
        self._ensure_ready()
        if self.retriever is not None:
            documents = self.retriever.invoke(query)
            return [_evidence_from_document(document) for document in documents]
        return self._retrieve_with_legacy_vector_store(query)

    async def aretrieve(self, query: str) -> list[dict[str, Any]]:
        """Asynchronously invoke the LangChain retrieval pipeline."""
        self._ensure_ready()
        if self.retriever is not None:
            documents = await self.retriever.ainvoke(query)
            return [_evidence_from_document(document) for document in documents]
        return await asyncio.to_thread(self._retrieve_with_legacy_vector_store, query)

    def _ensure_ready(self) -> None:
        status = self.vector_store.status
        if status == "not_initialized":
            raise VectorStoreNotInitialized("向量知识库尚未初始化")
        if status == "incompatible":
            raise VectorStoreSignatureMismatch("当前 Embedding 签名与生产索引不一致")

    def _retrieve_with_legacy_vector_store(self, query: str) -> list[dict[str, Any]]:
        # Compatibility path for injected vector stores that predate the
        # LangChain ``as_retriever`` interface. Production uses ``retriever``;
        # remove this path after downstream custom stores have migrated.
        query_vector = self.embedding_service.embed_query(query)
        hits = list(self.vector_store.search(query_vector, self.config.rag_top_k))
        chunks_by_id = self._chunks_by_ids(chunk_id for chunk_id, _ in hits)
        evidence: list[dict[str, Any]] = []
        seen: set[int] = set()
        for chunk_id, score in hits:
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            chunk = chunks_by_id.get(chunk_id)
            if chunk is None:
                continue
            evidence.append(_evidence_item(chunk, score, len(evidence) + 1))
        return self._apply_rerank(query, evidence)

    def _documents_to_evidence_documents(
        self, state: Mapping[str, Any]
    ) -> list[Document]:
        query = str(state["query"])
        candidate_documents = list(state["documents"])
        chunks_by_id = self._chunks_by_ids(
            _document_chunk_id(document) for document in candidate_documents
        )
        evidence: list[dict[str, Any]] = []
        seen: set[int] = set()
        for document in candidate_documents:
            chunk_id = _document_chunk_id(document)
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            chunk = chunks_by_id.get(chunk_id)
            if chunk is None:
                continue
            score = float(
                document.metadata.get(
                    "retrieval_score", document.metadata.get("score", 0.0)
                )
            )
            evidence.append(_evidence_item(chunk, score, len(evidence) + 1))

        return [
            _document_from_evidence(item)
            for item in self._apply_rerank(query, evidence)
        ]

    def _chunks_by_ids(self, chunk_ids: Iterable[int]) -> dict[int, dict[str, Any]]:
        normalized_ids = list(dict.fromkeys(int(chunk_id) for chunk_id in chunk_ids))
        if not normalized_ids:
            return {}

        get_chunks_by_ids = getattr(self.repository, "get_chunks_by_ids", None)
        if callable(get_chunks_by_ids):
            return get_chunks_by_ids(normalized_ids)

        # Compatibility fallback for injected repositories from older clients.
        return {
            int(chunk["id"]): chunk
            for chunk in self.repository.list_success_chunks()
            if int(chunk["id"]) in normalized_ids
        }

    def _apply_rerank(
        self, query: str, evidence: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if self.config.rerank_enabled:
            return self.rerank_service.rerank(query, evidence)
        return evidence


# Keep the existing import path stable while making the domain service the
# canonical implementation name for new code.
RetrievalService = DomainRetrievalService


def _evidence_item(
    chunk: Mapping[str, Any], score: float, rank_no: int
) -> dict[str, Any]:
    retrieval_score = min(1.0, max(0.0, float(score)))
    return {
        "chunk_id": int(chunk["id"]),
        "document_id": int(chunk["document_id"]),
        "file_name": str(chunk["file_name"]),
        "chunk_no": int(chunk["chunk_no"]),
        "content": str(chunk["content"]),
        "score": retrieval_score,
        "retrieval_score": retrieval_score,
        "rerank_score": None,
        "rank_no": rank_no,
    }


def _document_chunk_id(document: Document) -> int:
    value = document.metadata.get("chunk_id", document.id)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("检索 Document 缺少有效 chunk_id") from exc


def _document_from_evidence(item: Mapping[str, Any]) -> Document:
    chunk_id = int(item["chunk_id"])
    metadata = {
        "chunk_id": chunk_id,
        "document_id": int(item["document_id"]),
        "file_name": str(item["file_name"]),
        "chunk_no": int(item["chunk_no"]),
        "score": float(item["score"]),
        "retrieval_score": float(item["retrieval_score"]),
        "rerank_score": item.get("rerank_score"),
        "rank_no": int(item["rank_no"]),
    }
    return Document(
        id=str(chunk_id),
        page_content=str(item["content"]),
        metadata=metadata,
    )


def _evidence_from_document(document: Document) -> dict[str, Any]:
    metadata = document.metadata
    return {
        "chunk_id": int(metadata["chunk_id"]),
        "document_id": int(metadata["document_id"]),
        "file_name": str(metadata["file_name"]),
        "chunk_no": int(metadata["chunk_no"]),
        "content": document.page_content,
        "score": float(metadata["score"]),
        "retrieval_score": float(metadata["retrieval_score"]),
        "rerank_score": metadata.get("rerank_score"),
        "rank_no": int(metadata["rank_no"]),
    }
