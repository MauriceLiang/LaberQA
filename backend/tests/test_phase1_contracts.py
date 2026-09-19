import sqlite3
import tempfile
import unittest
from pathlib import Path

import httpx
from app.core.config import Settings, settings
from app.core.database import database_is_ready, initialize_database
from app.core.error_codes import ErrorCode
from app.main import app
from app.rag.embeddings import LangChainEmbeddingService
from app.rag.errors import EmbeddingUnavailableError
from app.repositories.evaluation_repository import EvaluationRepository
from app.repositories.retrieval_experiment_repository import (
    RetrievalExperimentRepository,
)
from app.repositories.retrieval_strategy_repository import RetrievalStrategyRepository
from app.schemas.contracts import (
    EvaluationCase,
    ExperimentConfig,
    ExperimentCreate,
    RetrievalStrategyCreate,
    RetrievalStrategyUpdate,
)
from app.services.retrieval_experiment_service import RetrievalExperimentService
from fastapi.testclient import TestClient
from pydantic import ValidationError

EXPECTED_OPERATIONS = {
    ("get", "/api/health"),
    ("post", "/api/documents/upload"),
    ("get", "/api/documents"),
    ("get", "/api/documents/{id}"),
    ("delete", "/api/documents/{id}"),
    ("post", "/api/documents/{id}/reimport"),
    ("get", "/api/documents/{id}/chunks"),
    ("post", "/api/sessions"),
    ("get", "/api/sessions"),
    ("get", "/api/sessions/{id}/messages"),
    ("post", "/api/chat/stream"),
    ("post", "/api/tools/material-checklist"),
    ("get", "/api/evaluations/cases"),
    ("post", "/api/evaluations/cases"),
    ("get", "/api/evaluations/cases/{id}"),
    ("patch", "/api/evaluations/cases/{id}"),
    ("delete", "/api/evaluations/cases/{id}"),
    ("post", "/api/evaluations/runs"),
    ("get", "/api/evaluations/runs"),
    ("get", "/api/evaluations/runs/{id}"),
    ("delete", "/api/evaluations/runs/{id}"),
    ("get", "/api/missing-knowledge"),
    ("patch", "/api/missing-knowledge/{id}"),
    ("get", "/api/retrieval-experiments"),
    ("post", "/api/retrieval-experiments"),
    ("post", "/api/retrieval-experiments/preview"),
    ("post", "/api/retrieval-experiments/{id}/copy"),
    ("get", "/api/retrieval-experiments/{id}/export"),
    ("post", "/api/retrieval-experiments/{id}/archive"),
    ("post", "/api/retrieval-experiments/{id}/restore"),
    ("get", "/api/retrieval-experiments/{id}"),
    ("delete", "/api/retrieval-experiments/{id}"),
    ("get", "/api/retrieval-strategies"),
    ("post", "/api/retrieval-strategies"),
    ("patch", "/api/retrieval-strategies/{id}/status"),
    ("get", "/api/retrieval-strategies/{id}/versions"),
    ("post", "/api/retrieval-strategies/{id}/versions/{version}/restore"),
    ("post", "/api/retrieval-strategies/{id}/archive"),
    ("post", "/api/retrieval-strategies/{id}/restore"),
    ("patch", "/api/retrieval-strategies/{id}"),
    ("delete", "/api/retrieval-strategies/{id}"),
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
            ("/api/evaluations/cases", "post"),
            ("/api/evaluations/cases/{id}", "get"),
            ("/api/evaluations/cases/{id}", "patch"),
            ("/api/evaluations/cases/{id}", "delete"),
            ("/api/evaluations/runs", "post"),
            ("/api/evaluations/runs", "get"),
            ("/api/evaluations/runs/{id}", "get"),
            ("/api/evaluations/runs/{id}", "delete"),
        ):
            self.assertNotIn("501", schema["paths"][path][method]["responses"])
        for path, method in (
            ("/api/retrieval-experiments", "get"),
            ("/api/retrieval-experiments", "post"),
            ("/api/retrieval-experiments/{id}", "get"),
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

    def test_invalid_experiment_config_uses_its_business_error_code(self) -> None:
        with TestClient(app) as client:
            response = client.post(
                "/api/retrieval-experiments",
                json={
                    "name": "invalid",
                    "strategy_ids": [1, 1],
                    "case_scope": "BUILTIN_BASELINE",
                    "case_ids": None,
                    "answer_style": "plain",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], ErrorCode.INVALID_EXPERIMENT_CONFIG)

    def test_experiment_requires_two_distinct_strategies(self) -> None:
        for strategy_ids in ([1], [1, 1]):
            with self.assertRaises(ValidationError):
                ExperimentCreate(
                    name="invalid",
                    strategy_ids=strategy_ids,
                    case_scope="BUILTIN_BASELINE",
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
            service = LangChainEmbeddingService(config, api_client=client)
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
            origin="BUILTIN",
            status="ACTIVE",
            version=1,
            created_at="2026-09-15T00:00:00Z",
            updated_at="2026-09-15T00:00:00Z",
            archived_at=None,
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
            "retrieval_strategy",
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

    def test_database_migrates_old_document_file_type_constraint(self) -> None:
        database_path = settings.database_path
        with sqlite3.connect(database_path) as connection:
            connection.execute(
                """
                CREATE TABLE document (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_name VARCHAR(255) NOT NULL,
                    file_type VARCHAR(20) NOT NULL
                        CHECK (file_type IN ('pdf', 'doc', 'docx', 'txt')),
                    file_path VARCHAR(500) NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'PROCESSING'
                        CHECK (status IN ('PROCESSING', 'SUCCESS', 'FAILED')),
                    chunk_count INTEGER NOT NULL DEFAULT 0 CHECK (chunk_count >= 0),
                    error_message VARCHAR(500),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                INSERT INTO document (
                    file_name, file_type, file_path, status, chunk_count
                )
                VALUES ('旧资料.txt', 'txt', '/tmp/old.txt', 'SUCCESS', 1)
                """
            )

        initialize_database()

        with sqlite3.connect(database_path) as connection:
            connection.execute(
                """
                INSERT INTO document (
                    file_name, file_type, file_path, status
                )
                VALUES ('新资料.md', 'md', '/tmp/new.md', 'PROCESSING')
                """
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM document WHERE file_type = 'md'"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM document WHERE file_name = '旧资料.txt'"
                ).fetchone()[0],
                1,
            )

    def test_retrieval_experiment_archive_and_export_lifecycle(self) -> None:
        initialize_database()
        EvaluationRepository(settings.database_path).create_case(
            {
                "topic": "测试用例",
                "expected_type": "ANSWER",
                "turns": ["测试问题"],
                "expected_points": ["测试要点"],
                "expected_sources": [],
                "should_show_compliance": False,
            }
        )
        repository = RetrievalExperimentRepository(settings.database_path)
        experiment = repository.create_experiment(
            "批次 A",
            1,
            {
                "answer_style": "plain",
                "case_scope": "SELECTED",
                "case_ids": [1],
                "case_snapshots": [],
                "configs": [
                    {
                        "chunk_size": 600,
                        "chunk_overlap": 100,
                        "top_k": 5,
                        "rerank_enabled": False,
                        "rerank_top_n": 5,
                        "score_threshold": 0.35,
                    }
                ],
                "embedding_signature": {
                    "embedding_provider": "local",
                    "embedding_model": "test",
                    "embedding_dimension": 3,
                    "normalize_embeddings": True,
                },
            },
        )
        repository.add_result(
            experiment["id"],
            {
                "config_index": 0,
                "case_id": 1,
                "status": "COMPLETED",
                "retrieved_sources": [{"file_name": "劳动法.docx"}],
                "source_hit": True,
                "correct": False,
                "refused": False,
                "retrieval_ms": 12,
                "error_message": None,
            },
        )
        repository.complete_experiment(
            experiment["id"],
            0,
            {
                "accuracy": 0.0,
                "reject_rate": None,
                "citation_hit_rate": 1.0,
                "avg_retrieval_ms": 12.0,
            },
        )
        service = object.__new__(RetrievalExperimentService)
        service.repository = repository

        archived = service.archive_experiment(experiment["id"])
        self.assertTrue(archived["archived_at"])
        self.assertEqual(
            repository.list_experiments(page=1, size=10, status=None)[0], []
        )
        self.assertEqual(
            len(
                repository.list_experiments(
                    page=1, size=10, status=None, include_archived=True
                )[0]
            ),
            1,
        )
        exported = service.export_experiment(experiment["id"])
        self.assertIn("实验名称", exported)
        self.assertIn("劳动法.docx", exported)

        restored = service.restore_experiment(experiment["id"])
        self.assertIsNone(restored["archived_at"])

    def test_retrieval_strategy_version_lifecycle(self) -> None:
        initialize_database()
        repository = RetrievalStrategyRepository(settings.database_path)
        service = object.__new__(RetrievalExperimentService)
        service.strategy_repository = repository
        config = ExperimentConfig(
            chunk_size=600,
            chunk_overlap=100,
            top_k=5,
            rerank_enabled=False,
            rerank_top_n=5,
            score_threshold=0.35,
        )
        created = service.create_strategy(
            RetrievalStrategyCreate(name="版本策略", description="初始", config=config)
        )
        self.assertEqual(created["version"], 1)
        updated = service.update_strategy(
            created["id"],
            RetrievalStrategyUpdate(
                name="版本策略 v2", description="修改后", config=config
            ),
        )
        self.assertEqual(updated["version"], 2)
        self.assertEqual(
            [item["version"] for item in service.list_strategy_versions(created["id"])],
            [2, 1],
        )
        restored = service.restore_strategy_version(created["id"], 1)
        self.assertEqual(restored["version"], 3)
        self.assertEqual(restored["name"], "版本策略")
        self.assertEqual(restored["description"], "初始")


if __name__ == "__main__":
    unittest.main()
