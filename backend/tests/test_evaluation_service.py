import asyncio
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_evaluation_service
from app.core.config import Settings, settings
from app.core.database import initialize_database
from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.main import app
from app.schemas.contracts import (
    EvaluationCaseCreate,
    EvaluationCaseUpdate,
    EvaluationRunCreate,
)
from app.services.evaluation_cases import fixed_evaluation_cases
from app.services.evaluation_service import EvaluationService
from app.services.llm import ModelUnavailableError


class FakeJudge:
    def __init__(
        self, *, answer: str = '{"correct":true,"context_retained":true}'
    ) -> None:
        self.answer = answer
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> str:
        self.calls.append(
            {"messages": messages, "json_mode": json_mode, "temperature": temperature}
        )
        return self.answer


class FakeChat:
    def __init__(
        self, *, fail_question: str | None = None, model_failure: bool = False
    ) -> None:
        self.llm_client = FakeJudge()
        self.fail_question = fail_question
        self.model_failure = model_failure
        self.calls: list[tuple[str, list[dict[str, str]]]] = []

    async def answer_once(
        self,
        question: str,
        history: list[dict[str, str]],
        answer_style: Any,
        *,
        mode: Any,
    ) -> dict[str, Any]:
        self.calls.append((question, list(history)))
        if self.model_failure:
            raise ModelUnavailableError("model down")
        if question == self.fail_question:
            raise RuntimeError("single item failed")
        refused = question.startswith("平台今天")
        return {
            "answer": "资料不足，无法可靠判断。"
            if refused
            else "劳动关系自用工之日起建立。",
            "refused": refused,
            "citations": []
            if refused
            else [
                {
                    "chunk_id": 1,
                    "document_id": 1,
                    "file_name": "法条文件.docx",
                    "chunk_no": 4,
                    "content": "劳动关系自用工之日起建立。",
                    "score": 0.9,
                    "retrieval_score": 0.9,
                    "rerank_score": None,
                    "rank_no": 1,
                }
            ],
            "rewritten_question": question,
            "retrieval_ms": 4,
            "compliance_shown": False,
        }


def _service(database_path: Path, chat: FakeChat | None = None) -> EvaluationService:
    config = Settings(
        database_url=f"sqlite:///{database_path}",
        llm_api_key="test-key",
        llm_base_url="https://llm.example.test/v1",
        llm_model="test-model",
    )
    service = EvaluationService(chat or FakeChat(), config)
    service.initialize()
    return service


def _create_database(database_path: Path) -> None:
    schema = Path(__file__).parents[1] / "app" / "core" / "schema.sql"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(schema.read_text(encoding="utf-8"))


def test_fixed_cases_have_the_documented_distribution_and_json_arrays() -> None:
    cases = fixed_evaluation_cases()
    assert len(cases) == 60
    assert (
        sum(
            case["expected_type"] == "ANSWER" and len(case["turns"]) == 1
            for case in cases
        )
        == 30
    )
    assert (
        sum(
            case["expected_type"] == "ANSWER" and len(case["turns"]) > 1
            for case in cases
        )
        == 10
    )
    assert sum(case["expected_type"] == "REJECT" for case in cases) == 20
    assert all(isinstance(case["turns"], list) for case in cases)


def test_run_executes_subset_calculates_metrics_and_does_not_write_chat_tables() -> (
    None
):
    with tempfile.TemporaryDirectory() as directory:
        database_path = Path(directory) / "eval.db"
        _create_database(database_path)
        chat = FakeChat()
        service = _service(database_path, chat)
        run = service.create_run(
            EvaluationRunCreate(name="subset", case_ids=[1, 41], answer_style="legal")
        )

        config_snapshot = service.get_run(run["id"])["config"]
        assert config_snapshot["langchain_version"]
        assert config_snapshot["chat_provider"] == "langchain_openai.ChatOpenAI"
        assert config_snapshot["splitter_type"] == (
            "app.rag.splitters.LegalTextSplitter"
        )
        assert config_snapshot["splitter_version"] == "legal-text-splitter-v1"
        assert config_snapshot["vectorstore_type"] == (
            "langchain_community.vectorstores.FAISS"
        )
        assert config_snapshot["retrieval_type"] == "similarity"
        assert config_snapshot["rerank_model"] is None

        asyncio.run(service.execute_run(run["id"]))

        detail = service.get_run(run["id"])
        assert detail["status"] == "COMPLETED"
        assert detail["progress_current"] == detail["progress_total"] == 2
        assert [item["status"] for item in detail["results"]] == [
            "COMPLETED",
            "COMPLETED",
        ]
        assert detail["results"][0]["source_hit"] is True
        assert detail["results"][1]["correct"] is True
        assert detail["metrics"] == {
            "accuracy": 1.0,
            "reject_rate": 1.0,
            "citation_hit_rate": 1.0,
            "multi_turn_pass_rate": None,
            "compliance_hit_rate": None,
        }
        assert chat.llm_client.calls[0]["temperature"] == 0
        with sqlite3.connect(database_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM message").fetchone()[0] == 0
            assert (
                connection.execute("SELECT COUNT(*) FROM citation").fetchone()[0] == 0
            )
            assert (
                connection.execute("SELECT COUNT(*) FROM missing_knowledge").fetchone()[
                    0
                ]
                == 0
            )


def test_multiturn_replays_prior_user_and_assistant_messages_in_memory() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database_path = Path(directory) / "eval.db"
        _create_database(database_path)
        chat = FakeChat()
        service = _service(database_path, chat)
        run = service.create_run(
            EvaluationRunCreate(name="multi", case_ids=[31], answer_style="plain")
        )

        asyncio.run(service.execute_run(run["id"]))

        assert len(chat.calls) == 2
        assert [item["role"] for item in chat.calls[1][1]] == ["user", "assistant"]
        assert chat.calls[1][1][1]["content"] == "劳动关系自用工之日起建立。"
        result = service.get_run(run["id"])["results"][0]
        assert result["multi_turn_correct"] is True
        assert service.get_run(run["id"])["metrics"]["multi_turn_pass_rate"] == 1.0


def test_delete_run_rejects_active_jobs_and_cascades_persisted_results() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database_path = Path(directory) / "eval.db"
        _create_database(database_path)
        service = _service(database_path)
        run = service.create_run(
            EvaluationRunCreate(name="delete", case_ids=[1], answer_style="plain")
        )

        with pytest.raises(AppError) as error:
            service.delete_run(run["id"])
        assert error.value.code == ErrorCode.INVALID_EVALUATION_RUN_STATE

        asyncio.run(service.execute_run(run["id"]))
        service.delete_run(run["id"])

        assert service.repository.get_run(run["id"]) is None
        with sqlite3.connect(database_path) as connection:
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM evaluation_run_case WHERE run_id = ?",
                    (run["id"],),
                ).fetchone()[0]
                == 0
            )
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM evaluation_result WHERE run_id = ?",
                    (run["id"],),
                ).fetchone()[0]
                == 0
            )
            assert (
                connection.execute("SELECT COUNT(*) FROM evaluation_case").fetchone()[0]
                == 60
            )


def test_item_error_is_saved_and_remaining_cases_continue() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database_path = Path(directory) / "eval.db"
        _create_database(database_path)
        case = fixed_evaluation_cases()[0]
        chat = FakeChat(fail_question=case["turns"][0])
        service = _service(database_path, chat)
        run = service.create_run(
            EvaluationRunCreate(
                name="item failure", case_ids=[1, 2], answer_style="plain"
            )
        )

        asyncio.run(service.execute_run(run["id"]))

        detail = service.get_run(run["id"])
        assert detail["status"] == "COMPLETED"
        assert [item["status"] for item in detail["results"]] == ["FAILED", "COMPLETED"]
        assert detail["results"][0]["error_message"] == "single item failed"
        assert detail["metrics"]["accuracy"] == 1.0


def test_global_model_error_fails_batch_and_stops_remaining_cases() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database_path = Path(directory) / "eval.db"
        _create_database(database_path)
        chat = FakeChat(model_failure=True)
        service = _service(database_path, chat)
        run = service.create_run(
            EvaluationRunCreate(
                name="model failure", case_ids=[1, 2], answer_style="plain"
            )
        )

        asyncio.run(service.execute_run(run["id"]))

        detail = service.get_run(run["id"])
        assert detail["status"] == "FAILED"
        assert detail["progress_current"] == 1
        assert len(detail["results"]) == 1
        assert detail["results"][0]["status"] == "FAILED"
        assert detail["metrics"] is None


def test_startup_recovery_marks_interrupted_run_failed() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database_path = Path(directory) / "eval.db"
        _create_database(database_path)
        service = _service(database_path)
        run = service.create_run(
            EvaluationRunCreate(name="interrupted", case_ids=[1], answer_style="plain")
        )

        service.initialize()

        detail = service.get_run(run["id"])
        assert detail["status"] == "FAILED"
        assert detail["error_message"] == "服务重启导致任务中断"


def test_custom_case_can_be_updated_and_archived_without_changing_run_snapshot() -> (
    None
):
    with tempfile.TemporaryDirectory() as directory:
        database_path = Path(directory) / "eval.db"
        _create_database(database_path)
        service = _service(database_path)
        case = service.create_case(
            EvaluationCaseCreate(
                topic="自定义主题",
                expected_type="ANSWER",
                turns=["原问题"],
                expected_points=["原要点"],
                expected_sources=[],
                should_show_compliance=False,
            )
        )

        updated = service.update_case(
            case["id"],
            EvaluationCaseUpdate(
                version=1,
                topic="更新主题",
                expected_type="ANSWER",
                turns=["新问题"],
                expected_points=["新要点"],
                expected_sources=[],
                should_show_compliance=True,
            ),
        )
        assert updated["version"] == 2
        run = service.create_run(
            EvaluationRunCreate(
                name="snapshot",
                case_ids=[case["id"]],
                answer_style="plain",
            )
        )
        snapshot = service.repository.run_cases(run["id"])[0]
        service.repository.complete_run(
            run["id"],
            {
                "accuracy": None,
                "reject_rate": None,
                "citation_hit_rate": None,
                "multi_turn_pass_rate": None,
                "compliance_hit_rate": None,
            },
        )

        archived = service.archive_case(case["id"])
        assert archived["status"] == "ARCHIVED"
        assert service.repository.get_cases()[-1]["id"] == 60
        assert (
            service.repository.get_case(case["id"], include_archived=True)["status"]
            == "ARCHIVED"
        )
        assert snapshot["topic"] == "更新主题"
        assert snapshot["version"] == 2


def test_builtin_case_can_be_updated_and_run_scope_is_explicit() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database_path = Path(directory) / "eval.db"
        _create_database(database_path)
        service = _service(database_path)

        updated = service.update_case(
            1,
            EvaluationCaseUpdate(
                version=1,
                topic="已修改的内置用例",
                expected_type="ANSWER",
                turns=["问题"],
                expected_points=["要点"],
                expected_sources=[],
                should_show_compliance=False,
            ),
        )
        assert updated["origin"] == "BUILTIN"
        assert updated["version"] == 2

        with pytest.raises(AppError) as error:
            service.archive_case(1)
        assert error.value.code == ErrorCode.BUILTIN_CASE_READ_ONLY

        baseline = service.create_run(
            EvaluationRunCreate(
                name="baseline",
                case_ids=None,
                answer_style="plain",
                case_scope="BUILTIN_BASELINE",
            )
        )
        assert baseline["case_count"] == 60
        assert (
            service.repository.get_run(baseline["id"])["config"]["case_scope"]
            == "BUILTIN_BASELINE"
        )


def test_api_lists_seed_cases_and_returns_accepted_run() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database_path = Path(directory) / "api.db"
        original_database_url = settings.database_url
        original_overrides = app.dependency_overrides.copy()
        settings.database_url = f"sqlite:///{database_path}"
        try:
            initialize_database()
            service = _service(database_path)
            app.dependency_overrides[get_evaluation_service] = lambda: service
            with TestClient(app) as client:
                cases_response = client.get("/api/evaluations/cases?size=100")
                assert cases_response.status_code == 200
                assert cases_response.json()["data"]["total"] == 60
                assert isinstance(
                    cases_response.json()["data"]["items"][0]["turns"], list
                )
                multi_turn_response = client.get(
                    "/api/evaluations/cases?size=100&is_multi_turn=true"
                )
                assert multi_turn_response.json()["data"]["total"] == 10
                reject_response = client.get(
                    "/api/evaluations/cases?size=100&expected_type=REJECT"
                )
                assert reject_response.json()["data"]["total"] == 20

                invalid_run = client.post(
                    "/api/evaluations/runs",
                    json={
                        "name": "invalid",
                        "case_ids": [999],
                        "answer_style": "plain",
                    },
                )
                assert invalid_run.status_code == 400
                assert invalid_run.json()["code"] == 40003

                response = client.post(
                    "/api/evaluations/runs",
                    json={
                        "name": "api subset",
                        "case_ids": [1],
                        "answer_style": "plain",
                    },
                )
                assert response.status_code == 202
                assert response.json()["data"]["status"] == "PENDING"
                assert response.json()["data"]["progress_total"] == 1
                run_id = response.json()["data"]["run_id"]
                runs_response = client.get("/api/evaluations/runs?page=1&size=10")
                assert runs_response.status_code == 200
                assert runs_response.json()["data"]["total"] == 1
                assert client.get(f"/api/evaluations/runs/{run_id}").status_code == 200
                assert client.get("/api/evaluations/runs/999").status_code == 404

                delete_response = client.delete(f"/api/evaluations/runs/{run_id}")
                assert delete_response.status_code == 200
                assert delete_response.json() == {
                    "code": 0,
                    "message": "deleted",
                    "data": None,
                }
                assert client.get(f"/api/evaluations/runs/{run_id}").status_code == 404

                active_run = service.create_run(
                    EvaluationRunCreate(
                        name="active", case_ids=[1], answer_style="plain"
                    )
                )
                active_delete = client.delete(
                    f"/api/evaluations/runs/{active_run['id']}"
                )
                assert active_delete.status_code == 409
                assert active_delete.json()["code"] == 40903
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(original_overrides)
            settings.database_url = original_database_url
