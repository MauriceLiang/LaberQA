from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.api.dependencies import get_retrieval_experiment_service
from app.core.config import Settings, settings
from app.main import app
from app.repositories.document_repository import DocumentRepository
from app.repositories.evaluation_repository import EvaluationRepository
from app.repositories.retrieval_experiment_repository import (
    RetrievalExperimentRepository,
)
from app.schemas.contracts import (
    EmbeddingSignature,
    ExperimentConfig,
    ExperimentCreate,
)
from app.services.chat_service import ChatService
from app.services.evaluation_service import EvaluationService
from app.services.missing_knowledge import MissingKnowledgeService
from app.services.rerank import RerankService
from app.services.retrieval import RetrievalService
from app.services.retrieval_experiment_service import (
    RetrievalExperimentService,
    _best_config,
)
from app.services.session_service import SessionService
from app.services.vector_store import VectorStoreService
from tests.support import AsyncClientChatModel


class FakeEmbeddingService:
    def __init__(self, model: str) -> None:
        self.model = model

    def signature(self, dimension: int | None = None) -> EmbeddingSignature:
        return EmbeddingSignature(
            embedding_provider="local",
            embedding_model=self.model,
            embedding_dimension=dimension or 2,
            normalize_embeddings=True,
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0]


class FakeChatClient:
    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> str:
        if json_mode:
            payload = json.loads(messages[-1]["content"])
            if "question" in payload and "evidence" in payload:
                return json.dumps({"sufficient": payload["question"] != "reject"})
            return json.dumps({"correct": True, "context_retained": True})
        return "劳动关系自用工之日起建立。"


def _create_database(database_path: Path) -> None:
    schema_path = Path(__file__).parents[1] / "app" / "core" / "schema.sql"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(schema_path.read_text(encoding="utf-8"))


def _cases() -> list[dict[str, Any]]:
    return [
        {
            "topic": "劳动合同",
            "expected_type": "ANSWER",
            "turns": ["可回答的劳动权益问题"],
            "expected_points": ["劳动关系自用工之日起建立"],
            # This chunk number belongs to the old production chunking profile.
            "expected_sources": [{"file_name": "law.txt", "chunk_no": 99}],
            "should_show_compliance": False,
        },
        {
            "topic": "其他",
            "expected_type": "REJECT",
            "turns": ["reject"],
            "expected_points": [],
            "expected_sources": [],
            "should_show_compliance": False,
        },
    ]


def _configs() -> list[ExperimentConfig]:
    return [
        ExperimentConfig(
            chunk_size=100,
            chunk_overlap=10,
            top_k=20,
            rerank_enabled=False,
            rerank_top_n=5,
            score_threshold=0,
        ),
        ExperimentConfig(
            chunk_size=120,
            chunk_overlap=10,
            top_k=20,
            rerank_enabled=False,
            rerank_top_n=5,
            score_threshold=0,
        ),
    ]


def _make_environment(
    directory: Path,
) -> tuple[
    RetrievalExperimentService,
    RetrievalExperimentRepository,
    Settings,
    Path,
]:
    database_path = directory / "experiments.db"
    _create_database(database_path)
    config = Settings(
        database_url=f"sqlite:///{database_path}",
        faiss_dir=directory / "faiss",
        chunk_size=600,
        chunk_overlap=100,
        rag_top_k=20,
        rerank_enabled=False,
        local_embedding_model="offline-test-embedding",
        embedding_batch_size=8,
    )
    embedding = FakeEmbeddingService(config.embedding_model)
    document_repository = DocumentRepository(database_path)
    evaluation_repository = EvaluationRepository(database_path)
    evaluation_repository.seed_cases(_cases())

    source_path = directory / "law.txt"
    source_path.write_text("劳动权益依据。" * 80, encoding="utf-8")
    document = document_repository.create_document(
        file_name="law.txt",
        file_type="txt",
        file_path=str(source_path),
        status="SUCCESS",
    )
    old_chunk = document_repository.insert_chunks(
        document["id"], [{"chunk_no": 99, "content": "旧分块配置的法条"}]
    )[0]
    document_repository.update_document(document["id"], status="SUCCESS", chunk_count=1)

    production_vector_store = VectorStoreService(
        config=config,
        embedding_service=embedding,
        index_dir=config.faiss_path / "production",
    )
    production_vector_store.rebuild_from_success_chunks(
        [(int(old_chunk["id"]), [1.0, 0.0])], embedding.signature(2)
    )
    retrieval_service = RetrievalService(
        config,
        repository=document_repository,
        embedding_service=embedding,
        vector_store=production_vector_store,
        rerank_service=RerankService(config),
    )
    chat_service = ChatService(
        SessionService(database_path=database_path),
        retrieval_service,
        config,
        chat_model=AsyncClientChatModel(FakeChatClient()),
        missing_knowledge_service=MissingKnowledgeService(database_path=database_path),
    )
    evaluation_service = EvaluationService(
        chat_service, config, repository=evaluation_repository
    )
    repository = RetrievalExperimentRepository(database_path)
    service = RetrievalExperimentService(
        chat_service,
        config,
        document_repository=document_repository,
        evaluation_repository=evaluation_repository,
        repository=repository,
        embedding_service=embedding,  # type: ignore[arg-type]
        evaluation_service=evaluation_service,
    )
    return service, repository, config, database_path


def _production_hashes(production_dir: Path) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(production_dir.iterdir())
        if path.is_file()
    }


def test_experiment_uses_isolated_rechunked_indexes_and_persists_case_metrics(
    tmp_path: Path,
) -> None:
    service, repository, config, database_path = _make_environment(tmp_path)
    production_dir = config.faiss_path / "production"
    production_before = _production_hashes(production_dir)
    progress: list[int] = []
    experiment = service.create_experiment(
        ExperimentCreate(
            name="offline retrieval comparison",
            case_ids=[1, 2],
            answer_style="plain",
            configs=_configs(),
        )
    )
    snapshot = repository.get_experiment(experiment["id"])["snapshot"]
    assert snapshot["runtime_config"]["langchain_version"]
    assert snapshot["runtime_config"]["vectorstore_type"] == (
        "langchain_community.vectorstores.FAISS"
    )
    assert snapshot["runtime_config"]["retrieval_type"] == "similarity"

    add_result = repository.add_result

    def track_progress(experiment_id: int, result: dict[str, Any]) -> None:
        add_result(experiment_id, result)
        current = repository.get_experiment(experiment_id)
        assert current is not None
        progress.append(current["progress_current"])

    repository.add_result = track_progress  # type: ignore[method-assign]
    asyncio.run(service.execute_experiment(experiment["id"]))

    detail = service.get_experiment(experiment["id"])
    assert detail["status"] == "COMPLETED"
    assert detail["runtime_config"] == snapshot["runtime_config"]
    assert detail["progress_current"] == detail["progress_total"] == 4
    assert progress == [1, 2, 3, 4]
    assert detail["embedding_signature"]["embedding_model"] == "offline-test-embedding"
    assert len(detail["results"]) == 4
    for config_index in range(2):
        answer_result = next(
            result
            for result in detail["results"]
            if result["config_index"] == config_index and result["case_id"] == 1
        )
        reject_result = next(
            result
            for result in detail["results"]
            if result["config_index"] == config_index and result["case_id"] == 2
        )
        assert answer_result["status"] == "COMPLETED"
        assert answer_result["source_hit"] is True
        assert answer_result["correct"] is True
        assert answer_result["retrieved_sources"]
        assert all(
            source["file_name"] == "law.txt" and source["chunk_no"] != 99
            for source in answer_result["retrieved_sources"]
        )
        assert reject_result["status"] == "COMPLETED"
        assert reject_result["refused"] is True
        assert reject_result["correct"] is True
        assert reject_result["source_hit"] is None

    assert len(detail["config_results"]) == 2
    for summary in detail["config_results"]:
        assert summary["accuracy"] == 1
        assert summary["reject_rate"] == 1
        assert summary["citation_hit_rate"] == 1
        assert summary["avg_retrieval_ms"] is not None
    selected_summary = detail["config_results"][detail["best_config_index"]]
    assert selected_summary["citation_hit_rate"] == max(
        item["citation_hit_rate"] for item in detail["config_results"]
    )

    experiment_dir = (
        config.faiss_path / "experiments" / f"experiment_{experiment['id']}"
    )
    profile_dirs = sorted(path for path in experiment_dir.iterdir() if path.is_dir())
    assert {path.name for path in profile_dirs} == {
        "chunk_100_overlap_10",
        "chunk_120_overlap_10",
    }
    assert all((path / "index.faiss").is_file() for path in profile_dirs)
    assert all((path / "index_meta.json").is_file() for path in profile_dirs)
    assert _production_hashes(production_dir) == production_before

    with sqlite3.connect(database_path) as connection:
        for table in (
            "session",
            "message",
            "citation",
            "tool_execution",
            "missing_knowledge",
            "evaluation_run",
            "evaluation_result",
        ):
            assert (
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
            )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM retrieval_experiment_result WHERE experiment_id = ?",
                (experiment["id"],),
            ).fetchone()[0]
            == 4
        )


def test_initialize_marks_pending_and_running_experiments_interrupted(
    tmp_path: Path,
) -> None:
    service, repository, _, _ = _make_environment(tmp_path)
    snapshot = {
        "answer_style": "plain",
        "case_ids": [1],
        "configs": [_configs()[0].model_dump(mode="json")],
        "embedding_signature": {
            "embedding_provider": "local",
            "embedding_model": "offline-test-embedding",
            "embedding_dimension": 2,
            "normalize_embeddings": True,
        },
    }
    pending = repository.create_experiment("pending", 1, snapshot)
    running = repository.create_experiment("running", 1, snapshot)
    repository.set_running(running["id"])

    service.initialize()

    for experiment_id in (pending["id"], running["id"]):
        recovered = repository.get_experiment(experiment_id)
        assert recovered is not None
        assert recovered["status"] == "FAILED"
        assert recovered["error_message"] == "服务重启导致任务中断"
        assert recovered["progress_current"] == 0


def test_best_config_uses_metric_priority_latency_then_stable_index() -> None:
    def choose(config_results: list[dict[str, Any]]) -> int:
        return _best_config(
            config_results,
            [
                {"config_index": item["config_index"], "status": "COMPLETED"}
                for item in config_results
            ],
        )  # type: ignore[return-value]

    assert (
        choose(
            [
                {
                    "config_index": 0,
                    "citation_hit_rate": 0.8,
                    "accuracy": 1,
                    "reject_rate": 1,
                    "avg_retrieval_ms": 1,
                },
                {
                    "config_index": 1,
                    "citation_hit_rate": 0.9,
                    "accuracy": 0,
                    "reject_rate": 0,
                    "avg_retrieval_ms": 100,
                },
            ]
        )
        == 1
    )
    assert (
        choose(
            [
                {
                    "config_index": 0,
                    "citation_hit_rate": 0.9,
                    "accuracy": 0.8,
                    "reject_rate": 1,
                    "avg_retrieval_ms": 1,
                },
                {
                    "config_index": 1,
                    "citation_hit_rate": 0.9,
                    "accuracy": 0.9,
                    "reject_rate": 0,
                    "avg_retrieval_ms": 100,
                },
            ]
        )
        == 1
    )
    assert (
        choose(
            [
                {
                    "config_index": 0,
                    "citation_hit_rate": 0.9,
                    "accuracy": 0.9,
                    "reject_rate": 0.8,
                    "avg_retrieval_ms": 100,
                },
                {
                    "config_index": 1,
                    "citation_hit_rate": 0.9,
                    "accuracy": 0.9,
                    "reject_rate": 0.7,
                    "avg_retrieval_ms": 1,
                },
            ]
        )
        == 0
    )
    assert (
        choose(
            [
                {
                    "config_index": 0,
                    "citation_hit_rate": 0.9,
                    "accuracy": 0.9,
                    "reject_rate": 0.8,
                    "avg_retrieval_ms": 100,
                },
                {
                    "config_index": 1,
                    "citation_hit_rate": 0.9,
                    "accuracy": 0.9,
                    "reject_rate": 0.8,
                    "avg_retrieval_ms": 10,
                },
            ]
        )
        == 1
    )
    assert (
        choose(
            [
                {
                    "config_index": 1,
                    "citation_hit_rate": 0.9,
                    "accuracy": 0.9,
                    "reject_rate": 0.8,
                    "avg_retrieval_ms": 10,
                },
                {
                    "config_index": 0,
                    "citation_hit_rate": 0.9,
                    "accuracy": 0.9,
                    "reject_rate": 0.8,
                    "avg_retrieval_ms": 10,
                },
            ]
        )
        == 0
    )


def test_experiment_endpoints_accept_and_return_the_completed_job(
    tmp_path: Path,
) -> None:
    service, _, config, _ = _make_environment(tmp_path)
    original_database_url = settings.database_url
    original_faiss_dir = settings.faiss_dir
    original_upload_dir = settings.upload_dir
    original_embedding_model = settings.local_embedding_model
    original_overrides = app.dependency_overrides.copy()
    settings.database_url = config.database_url
    settings.faiss_dir = config.faiss_dir
    settings.upload_dir = tmp_path / "uploads"
    settings.local_embedding_model = config.local_embedding_model
    app.dependency_overrides[get_retrieval_experiment_service] = lambda: service
    try:
        with TestClient(app) as client:
            initial = client.get("/api/retrieval-experiments?page=1&size=10")
            accepted = client.post(
                "/api/retrieval-experiments",
                json={
                    "name": "API smoke experiment",
                    "case_ids": [1, 2],
                    "answer_style": "plain",
                    "configs": [_configs()[0].model_dump(mode="json")],
                },
            )
            experiment_id = accepted.json()["data"]["experiment_id"]
            detail = client.get(f"/api/retrieval-experiments/{experiment_id}")
    finally:
        settings.database_url = original_database_url
        settings.faiss_dir = original_faiss_dir
        settings.upload_dir = original_upload_dir
        settings.local_embedding_model = original_embedding_model
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)

    assert initial.status_code == 200
    assert initial.json()["data"]["total"] == 0
    assert accepted.status_code == 202
    assert accepted.json()["data"]["status"] == "PENDING"
    assert accepted.json()["data"]["progress_total"] == 2
    assert detail.status_code == 200
    assert detail.json()["data"]["status"] == "COMPLETED"
    assert detail.json()["data"]["progress_current"] == 2
    assert detail.json()["data"]["runtime_config"]["retrieval_type"] == "similarity"
    assert len(detail.json()["data"]["config_results"]) == 1
