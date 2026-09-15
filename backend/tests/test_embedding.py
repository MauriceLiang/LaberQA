import json
import unittest

import httpx

from app.core.config import Settings
from app.services.embedding import (
    ApiEmbeddingProvider,
    EmbeddingService,
    EmbeddingUnavailableError,
    LocalEmbeddingProvider,
)


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

        with unittest.mock.patch(
            "app.services.embedding._load_model", return_value=Model()
        ):
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


if __name__ == "__main__":
    unittest.main()
