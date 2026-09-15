import sqlite3
import tempfile
import unittest
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.core.database import database_is_ready, initialize_database
from app.main import app
from app.schemas.contracts import EvaluationCase, ExperimentConfig
from app.services.embedding import EmbeddingService, EmbeddingUnavailableError

EXPECTED_OPERATIONS = {
    ("get", "/api/health"),
    ("post", "/api/documents/upload"),
    ("get", "/api/documents"),
    ("get", "/api/documents/{id}"),
    ("post", "/api/documents/{id}/reimport"),
    ("get", "/api/documents/{id}/chunks"),
    ("post", "/api/sessions"),
    ("get", "/api/sessions/{id}/messages"),
    ("post", "/api/chat/stream"),
    ("post", "/api/tools/material-checklist"),
    ("get", "/api/evaluations/cases"),
    ("post", "/api/evaluations/runs"),
    ("get", "/api/evaluations/runs"),
    ("get", "/api/evaluations/runs/{id}"),
    ("get", "/api/missing-knowledge"),
    ("patch", "/api/missing-knowledge/{id}"),
    ("get", "/api/retrieval-experiments"),
    ("post", "/api/retrieval-experiments"),
    ("get", "/api/retrieval-experiments/{id}"),
}


class Phase1ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_directory = tempfile.TemporaryDirectory()
        self.original_database_url = settings.database_url
        settings.database_url = (
            f"sqlite:///{Path(self.database_directory.name) / 'test.db'}"
        )

    def tearDown(self) -> None:
        settings.database_url = self.original_database_url
        self.database_directory.cleanup()

    def test_openapi_contains_all_rest_operations(self) -> None:
        schema = app.openapi()
        operations = {
            (method, path)
            for path, path_item in schema["paths"].items()
            for method in path_item
            if method in {"get", "post", "patch", "put", "delete"}
        }
        self.assertEqual(operations, EXPECTED_OPERATIONS)

        upload = schema["paths"]["/api/documents/upload"]["post"]
        self.assertIn("multipart/form-data", upload["requestBody"]["content"])
        chat = schema["paths"]["/api/chat/stream"]["post"]
        self.assertIn("text/event-stream", chat["responses"]["200"]["content"])
        for path, method in (
            ("/api/sessions", "post"),
            ("/api/sessions/{id}/messages", "get"),
            ("/api/chat/stream", "post"),
            ("/api/missing-knowledge", "get"),
            ("/api/missing-knowledge/{id}", "patch"),
        ):
            self.assertNotIn("501", schema["paths"][path][method]["responses"])
        for path, method in (
            ("/api/evaluations/cases", "get"),
            ("/api/evaluations/runs", "post"),
            ("/api/evaluations/runs", "get"),
            ("/api/evaluations/runs/{id}", "get"),
        ):
            self.assertNotIn("501", schema["paths"][path][method]["responses"])

    def test_validation_uses_envelope_and_exposes_request_id(self) -> None:
        with TestClient(app) as client:
            response = client.get(
                "/api/documents?page=0",
                headers={"Origin": "http://127.0.0.1:5173"},
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json(),
            {"code": 40003, "message": "请求参数不合法", "data": None},
        )
        self.assertTrue(response.headers["x-request-id"])
        self.assertEqual(
            response.headers["access-control-expose-headers"], "X-Request-ID"
        )

    def test_session_route_creates_a_session(self) -> None:
        with TestClient(app) as client:
            response = client.post("/api/sessions", json={})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["code"], 0)
        self.assertIn("id", response.json()["data"])

    def test_unknown_route_uses_unified_not_found_message(self) -> None:
        with TestClient(app) as client:
            response = client.get("/api/not-a-route")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {"code": 40003, "message": "请求路径不存在", "data": None},
        )

    def test_openapi_freezes_experiment_embedding_signature(self) -> None:
        schema = app.openapi()
        experiment_detail = schema["components"]["schemas"]["ExperimentDetail"]
        self.assertIn("embedding_signature", experiment_detail["properties"])

    def test_settings_report_the_selected_embedding_model(self) -> None:
        api_settings = Settings(
            embedding_provider="api",
            embedding_api_key="secret",
            embedding_base_url="https://embedding.example.test/v1",
            embedding_api_model="embedding-model",
        )
        self.assertEqual(api_settings.embedding_model, "embedding-model")
        self.assertEqual(Settings().embedding_model, "BAAI/bge-small-zh-v1.5")

    def test_health_reports_the_configured_embedding_model(self) -> None:
        original_provider = settings.embedding_provider
        original_model = settings.embedding_api_model
        settings.embedding_provider = "api"
        settings.embedding_api_model = "embedding-model"
        try:
            with TestClient(app) as client:
                response = client.get("/api/health")
        finally:
            settings.embedding_provider = original_provider
            settings.embedding_api_model = original_model

        self.assertEqual(response.json()["data"]["embedding_model"], "embedding-model")

    def test_api_embedding_does_not_silently_fall_back_to_local(self) -> None:
        config = Settings(
            embedding_provider="api",
            embedding_api_key="test-key",
            embedding_base_url="https://example.test/v1",
            embedding_api_model="test-embedding",
        )
        with httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(503))
        ) as client:
            service = EmbeddingService(config, api_client=client)
            with self.assertRaises(EmbeddingUnavailableError):
                service.embed_documents(["测试文本"])

    def test_experiment_constraints_and_utc_serialization(self) -> None:
        with self.assertRaises(ValidationError):
            ExperimentConfig(
                chunk_size=400,
                chunk_overlap=400,
                top_k=5,
                rerank_enabled=True,
                rerank_top_n=6,
                score_threshold=0.35,
            )

        case = EvaluationCase(
            id=1,
            topic="工资",
            expected_type="ANSWER",
            turns=["欠薪怎么办？"],
            expected_points=["保留工资支付证据"],
            expected_sources=[{"file_name": "劳动合同法.pdf", "chunk_no": None}],
            should_show_compliance=True,
        )
        self.assertEqual(case.model_dump(mode="json")["turns"], ["欠薪怎么办？"])
        self.assertNotIn("expected_answer", case.model_dump_json())

    def test_database_initializes_all_core_tables_and_chunk_unique_key(self) -> None:
        expected_tables = {
            "document",
            "chunk",
            "session",
            "message",
            "citation",
            "tool_execution",
            "evaluation_case",
            "evaluation_run",
            "evaluation_result",
            "missing_knowledge",
            "retrieval_experiment",
            "retrieval_experiment_result",
        }
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "phase1.db"
            original_url = settings.database_url
            settings.database_url = f"sqlite:///{database_path}"
            try:
                initialize_database()
                self.assertTrue(database_is_ready())
            finally:
                settings.database_url = original_url

            with sqlite3.connect(database_path) as connection:
                actual_tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                self.assertTrue(expected_tables.issubset(actual_tables))
                indexes = connection.execute("PRAGMA index_list('chunk')").fetchall()
                self.assertTrue(any(row[2] for row in indexes))
                columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info('evaluation_case')"
                    )
                }
                self.assertTrue(
                    {
                        "turns_json",
                        "expected_points_json",
                        "expected_sources_json",
                    }.issubset(columns)
                )


if __name__ == "__main__":
    unittest.main()
