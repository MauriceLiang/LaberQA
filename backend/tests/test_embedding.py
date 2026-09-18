import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from langchain_core.embeddings import Embeddings

from app.core.config import Settings, settings
from app.services.embedding import (
    ApiEmbeddingProvider,
    EmbeddingService,
    EmbeddingUnavailableError,
    LocalEmbeddingProvider,
    local_embedding_is_cached,
)
from app.services.vector_store import VectorStoreService


class ApiEmbeddingProviderTests(unittest.TestCase):
    def test_posts_openai_compatible_request_and_normalizes_vectors(self) -> None:
        requests: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": 1, "embedding": [0.0, 2.0]},
                        {"index": 0, "embedding": [3.0, 4.0]},
                    ]
                },
            )

        config = Settings(
            embedding_provider="api",
            embedding_api_key="test-key",
            embedding_base_url="https://example.test/v1/",
            embedding_api_model="test-embedding",
            embedding_normalize=True,
        )
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            service = EmbeddingService(config, api_client=client)
            vectors = service.embed_documents(["第一条", "第二条"])

        self.assertEqual(str(requests[0].url), "https://example.test/v1/embeddings")
        self.assertEqual(requests[0].headers["authorization"], "Bearer test-key")
        self.assertEqual(
            json.loads(requests[0].content),
            {"model": "test-embedding", "input": ["第一条", "第二条"]},
        )
        self.assertEqual(vectors, [[0.6, 0.8], [0.0, 1.0]])
        self.assertEqual(service.signature().embedding_dimension, 2)

    def test_api_provider_reports_failures_without_local_fallback(self) -> None:
        def fail(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        config = Settings(
            embedding_provider="api",
            embedding_api_key="test-key",
            embedding_base_url="https://example.test/v1",
            embedding_api_model="test-embedding",
        )
        with httpx.Client(transport=httpx.MockTransport(fail)) as client:
            service = EmbeddingService(config, api_client=client)
            with self.assertRaises(EmbeddingUnavailableError):
                service.embed_query("测试")

    def test_api_signature_requires_a_returned_dimension(self) -> None:
        provider = ApiEmbeddingProvider(
            Settings(
                embedding_provider="api",
                embedding_api_key="test-key",
                embedding_base_url="https://example.test/v1",
                embedding_api_model="test-embedding",
            )
        )

        with self.assertRaisesRegex(RuntimeError, "维度尚未"):
            EmbeddingService(provider=provider).signature()


class LocalEmbeddingProviderTests(unittest.TestCase):
    def test_uses_local_model_and_returns_dimension(self) -> None:
        class Model:
            def encode(self, texts: list[str], **kwargs: object) -> object:
                return _Vectors([[1.0, 0.0], [0.0, 1.0]])

        class _Vectors(list):
            def tolist(self) -> list[list[float]]:
                return list(self)

        with patch("app.services.embedding._load_model", return_value=Model()):
            config = Settings(
                local_embedding_model="local-test",
                local_embedding_device="cpu",
                embedding_batch_size=4,
            )
            service = EmbeddingService(provider=LocalEmbeddingProvider(config))
            self.assertEqual(
                service.embed_documents(["第一条", "第二条"]),
                [[1.0, 0.0], [0.0, 1.0]],
            )
            self.assertEqual(service.signature().embedding_dimension, 2)

    def test_rejects_empty_input(self) -> None:
        service = EmbeddingService(
            provider=LocalEmbeddingProvider(Settings(local_embedding_device="cpu"))
        )

        with self.assertRaisesRegex(ValueError, "不能为空"):
            service.embed_query("  ")


class LangChainEmbeddingServiceTests(unittest.TestCase):
    def test_default_service_builds_langchain_embeddings_lazily(self) -> None:
        class FakeEmbeddings(Embeddings):
            def embed_documents(self, texts: list[str]) -> list[list[float]]:
                return [[1.0, 0.0] for _ in texts]

            def embed_query(self, text: str) -> list[float]:
                return [1.0, 0.0]

        config = Settings(
            _env_file=None,
            embedding_provider="local",
            embedding_normalize=False,
        )
        with patch(
            "app.services.embedding.build_embeddings",
            return_value=FakeEmbeddings(),
        ) as factory:
            service = EmbeddingService(config)
            self.assertIsInstance(service, Embeddings)
            self.assertIsInstance(service.embeddings, Embeddings)
            factory.assert_not_called()

            self.assertEqual(service.embed_query("测试"), [1.0, 0.0])

        factory.assert_called_once_with(config, http_client=None)
        self.assertEqual(service.signature().embedding_dimension, 2)


@pytest.mark.skipif(
    os.getenv("LABORQA_RUN_LOCAL_BGE_INTEGRATION") != "1",
    reason="requires a compatible local BGE and FAISS/Torch OpenMP runtime",
)
def test_cached_bge_embeddings_round_trip_through_faiss(tmp_path: Path) -> None:
    if not local_embedding_is_cached():
        pytest.skip("local BGE model is not cached")

    config = Settings(
        _env_file=None,
        local_embedding_model=settings.local_embedding_model,
        local_embedding_device="cpu",
        embedding_batch_size=32,
        embedding_normalize=True,
        faiss_dir=tmp_path / "faiss",
    )
    embedding = EmbeddingService(config)
    texts = [
        "劳动者工资应当按月足额支付，用人单位拖欠工资的，应当依法处理。",
        "劳动者依法享有带薪年休假，用人单位应安排休假。",
    ]
    vectors = embedding.embed_documents(texts)
    query = embedding.embed_query("用人单位拖欠劳动者工资怎么办？")
    store = VectorStoreService(
        config,
        embedding_service=embedding,
        index_dir=tmp_path / "faiss" / "production",
    )
    store.add(list(zip((1, 2), vectors, strict=True)))

    assert len(query) == len(vectors[0]) == 512
    assert store.search(query, 2)[0][0] == 1

    reloaded = VectorStoreService(
        config,
        embedding_service=embedding,
        index_dir=tmp_path / "faiss" / "production",
    )
    assert reloaded.load() is True


if __name__ == "__main__":
    unittest.main()
