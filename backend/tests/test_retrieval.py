import asyncio
from typing import Any

import pytest
from langchain_core.documents import Document
from langchain_core.runnables import Runnable, RunnableLambda

from app.core.config import Settings
from app.services.rerank import RerankService
from app.services.retrieval import DomainRetrievalService, RetrievalService
from app.services.vector_store import VectorStoreNotInitialized, VectorStoreService


class FakeEmbedding:
    def embed_query(self, query: str) -> list[float]:
        self.query = query
        return [0.1, 0.2]


class UnreadyVectorStore:
    status = "not_initialized"

    def as_retriever(self, **_: Any) -> Runnable[Any, list[Document]]:
        return RunnableLambda(lambda _query: [])


class FailingEmbedding:
    def embed_query(self, query: str) -> list[float]:
        raise AssertionError("embedding should not run without an index")


class FakeVectorStore:
    status = "ready"

    def __init__(self) -> None:
        self.query_vector: list[float] | None = None
        self.top_k: int | None = None
        self.embedding_service: FakeEmbedding | None = None

    def as_retriever(
        self, *, search_kwargs: dict[str, Any]
    ) -> Runnable[Any, list[Document]]:
        self.top_k = int(search_kwargs["k"])
        return RunnableLambda(self._retrieve)

    def _retrieve(self, query: str) -> list[Document]:
        if self.embedding_service is None:
            raise AssertionError("embedding service should be injected")
        hits = self.search(
            self.embedding_service.embed_query(query),
            self.top_k or 0,
        )
        return [
            Document(
                id=str(chunk_id),
                page_content="",
                metadata={
                    "chunk_id": chunk_id,
                    "score": score,
                    "retrieval_score": score,
                },
            )
            for chunk_id, score in hits
        ]

    def search(self, query_vector: list[float], top_k: int) -> list[tuple[int, float]]:
        self.query_vector = query_vector
        self.top_k = top_k
        return [(2, 0.91), (99, 0.88), (1, 0.72), (2, 0.61)]


class FakeRepository:
    def __init__(self) -> None:
        self.requested_chunk_ids: list[int] = []
        self.list_success_chunks_calls = 0

    def _chunks(self) -> list[dict[str, Any]]:
        return [
            {
                "id": 1,
                "document_id": 8,
                "file_name": "劳动法.txt",
                "chunk_no": 1,
                "content": "证据一",
            },
            {
                "id": 2,
                "document_id": 9,
                "file_name": "劳动合同法.pdf",
                "chunk_no": 3,
                "content": "证据二",
            },
        ]

    def list_success_chunks(self) -> list[dict[str, Any]]:
        self.list_success_chunks_calls += 1
        return self._chunks()

    def get_chunks_by_ids(self, chunk_ids: list[int]) -> dict[int, dict[str, Any]]:
        self.requested_chunk_ids = list(chunk_ids)
        chunks = self._chunks()
        return {int(chunk["id"]): chunk for chunk in chunks if chunk["id"] in chunk_ids}


class FakeCrossEncoder:
    def __init__(self, scores: list[float]) -> None:
        self.scores = scores
        self.pairs: list[tuple[str, str]] = []

    def predict(self, sentences: list[tuple[str, str]]) -> list[float]:
        self.pairs = sentences
        return self.scores


def test_retrieval_maps_only_successful_chunks_and_preserves_faiss_order() -> None:
    config = Settings(database_url="sqlite:////tmp/retrieval-test.db", rag_top_k=4)
    embedding = FakeEmbedding()
    vector_store = FakeVectorStore()
    repository = FakeRepository()
    service = RetrievalService(
        config,
        repository=repository,
        embedding_service=embedding,
        vector_store=vector_store,
    )

    evidence = service.retrieve("测试问题")

    assert embedding.query == "测试问题"
    assert vector_store.query_vector == [0.1, 0.2]
    assert vector_store.top_k == 4
    assert repository.requested_chunk_ids == [2, 99, 1]
    assert repository.list_success_chunks_calls == 0
    assert [item["chunk_id"] for item in evidence] == [2, 1]
    assert [item["rank_no"] for item in evidence] == [1, 2]
    assert evidence[0]["file_name"] == "劳动合同法.pdf"
    assert evidence[0]["retrieval_score"] == evidence[0]["score"] == 0.91
    assert evidence[0]["rerank_score"] is None


def test_domain_retrieval_uses_langchain_vectorstore_retriever_and_sqlite_source(
    tmp_path: Any,
) -> None:
    config = Settings(
        _env_file=None,
        database_url="sqlite:////tmp/domain-retrieval-test.db",
        rag_top_k=2,
        faiss_dir=tmp_path / "faiss",
    )
    vector_store = VectorStoreService(
        config,
        embedding_service=FakeEmbedding(),
        index_dir=tmp_path / "faiss" / "production",
    )
    vector_store.add([(1, [0.1, 0.2]), (2, [0.2, 0.1])])
    service = DomainRetrievalService(
        config,
        repository=FakeRepository(),
        embedding_service=FakeEmbedding(),
        vector_store=vector_store,
    )

    assert isinstance(service.retriever, Runnable)
    evidence = asyncio.run(service.aretrieve("测试问题"))

    assert [item["chunk_id"] for item in evidence] == [1, 2]
    assert evidence[0]["content"] == "证据一"
    assert evidence[0]["retrieval_score"] == pytest.approx(1.0)
    assert evidence[1]["document_id"] == 9
    assert RetrievalService is DomainRetrievalService


def test_retrieval_rejects_missing_index_before_loading_embedding_model() -> None:
    config = Settings(database_url="sqlite:////tmp/retrieval-unready-test.db")
    service = RetrievalService(
        config,
        repository=FakeRepository(),
        embedding_service=FailingEmbedding(),
        vector_store=UnreadyVectorStore(),
    )

    with pytest.raises(VectorStoreNotInitialized):
        service.retrieve("测试问题")


def test_enabled_reranker_resorts_and_truncates_evidence() -> None:
    config = Settings(
        database_url="sqlite:////tmp/retrieval-rerank-test.db",
        rag_top_k=4,
        rerank_enabled=True,
        rerank_top_n=1,
    )
    model = FakeCrossEncoder([-2.0, 1.0])
    service = RetrievalService(
        config,
        repository=FakeRepository(),
        embedding_service=FakeEmbedding(),
        vector_store=FakeVectorStore(),
        rerank_service=RerankService(config, model=model),
    )

    evidence = service.retrieve("测试问题")

    assert model.pairs == [
        ("测试问题", "证据二"),
        ("测试问题", "证据一"),
    ]
    assert [item["chunk_id"] for item in evidence] == [1]
    assert evidence[0]["retrieval_score"] == 0.72
    assert evidence[0]["rerank_score"] == evidence[0]["score"]
    assert evidence[0]["rank_no"] == 1


def test_rerank_failure_keeps_vector_order_and_original_scores() -> None:
    config = Settings(
        database_url="sqlite:////tmp/retrieval-rerank-fail-test.db",
        rag_top_k=4,
        rerank_enabled=True,
        rerank_top_n=4,
    )

    class FailingCrossEncoder:
        def predict(self, sentences: list[tuple[str, str]]) -> list[float]:
            raise RuntimeError("model is not cached")

    service = RetrievalService(
        config,
        repository=FakeRepository(),
        embedding_service=FakeEmbedding(),
        vector_store=FakeVectorStore(),
        rerank_service=RerankService(config, model=FailingCrossEncoder()),
    )

    evidence = service.retrieve("测试问题")

    assert [item["chunk_id"] for item in evidence] == [2, 1]
    assert [item["rerank_score"] for item in evidence] == [None, None]
    assert [item["score"] for item in evidence] == [0.91, 0.72]
