"""Asynchronous evaluation and test-case management without production session writes."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from langchain_core.exceptions import OutputParserException
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.core.config import Settings, settings
from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.rag.providers import ensure_chat_model
from app.repositories.evaluation_repository import EvaluationRepository
from app.schemas.contracts import (
    AnswerStyle,
    EvaluationCaseCreate,
    EvaluationCaseOrigin,
    EvaluationCaseScope,
    EvaluationCaseStatus,
    EvaluationCaseUpdate,
    EvaluationRunCreate,
)
from app.services.chat_service import ChatService
from app.services.embedding import EmbeddingUnavailableError
from app.services.evaluation_cases import fixed_evaluation_cases
from app.services.llm import ModelUnavailableError
from app.services.missing_knowledge import ExecutionMode
from app.services.vector_store import (
    VectorStoreNotInitialized,
    VectorStorePersistenceError,
    VectorStoreSignatureMismatch,
)

logger = logging.getLogger(__name__)
_EVALUATOR_PROMPT_VERSION = "evaluation_judge_v1"
_RESTART_ERROR = "服务重启导致任务中断"


class EvaluationService:
    def __init__(
        self,
        chat_service: ChatService,
        config: Settings = settings,
        *,
        repository: EvaluationRepository | None = None,
    ) -> None:
        self.chat_service = chat_service
        self.config = config
        self.repository = repository or EvaluationRepository(config.database_path)
        self.evaluator_prompt = (
            Path(__file__).resolve().parents[1] / "prompts" / "evaluation_judge.txt"
        ).read_text(encoding="utf-8")

    def initialize(self) -> None:
        self.repository.seed_cases(fixed_evaluation_cases())
        self.repository.recover_interrupted_runs()

    def list_cases(
        self,
        *,
        page: int,
        size: int,
        topic: str | None,
        expected_type: str | None,
        is_multi_turn: bool | None,
        origin: str | None,
        status: str | None,
        include_archived: bool,
    ) -> tuple[list[dict[str, Any]], int]:
        return self.repository.list_cases(
            page=page,
            size=size,
            topic=topic,
            expected_type=expected_type,
            is_multi_turn=is_multi_turn,
            origin=origin,
            status=status,
            include_archived=include_archived,
        )

    def create_case(self, payload: EvaluationCaseCreate) -> dict[str, Any]:
        return self.repository.create_case(payload.model_dump(mode="json"))

    def get_case(
        self, case_id: int, *, include_archived: bool = False
    ) -> dict[str, Any]:
        case = self.repository.get_case(case_id, include_archived=include_archived)
        if case is None:
            raise AppError(
                ErrorCode.EVALUATION_CASE_NOT_FOUND,
                "评测用例不存在",
                http_status=404,
            )
        return case

    def update_case(
        self, case_id: int, payload: EvaluationCaseUpdate
    ) -> dict[str, Any]:
        current = self.get_case(case_id, include_archived=True)
        if current["status"] != EvaluationCaseStatus.ACTIVE.value:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                "已归档的评测用例不能编辑",
                http_status=409,
            )
        if current["version"] != payload.version:
            raise AppError(
                ErrorCode.CASE_VERSION_CONFLICT,
                "评测用例已被其他操作修改，请刷新后重试",
                http_status=409,
            )
        updated = self.repository.update_case(
            case_id, payload.version, payload.model_dump(mode="json")
        )
        if updated is None:
            raise AppError(
                ErrorCode.CASE_VERSION_CONFLICT,
                "评测用例已被其他操作修改，请刷新后重试",
                http_status=409,
            )
        return updated

    def archive_case(self, case_id: int) -> dict[str, Any]:
        current = self.get_case(case_id, include_archived=True)
        if current["origin"] == EvaluationCaseOrigin.BUILTIN.value:
            raise AppError(
                ErrorCode.BUILTIN_CASE_READ_ONLY,
                "内置评测用例不能删除",
                http_status=409,
            )
        if current["status"] == EvaluationCaseStatus.ARCHIVED.value:
            return current
        if self.repository.has_active_run(case_id):
            raise AppError(
                ErrorCode.CASE_IN_ACTIVE_RUN,
                "评测用例正在运行中的批次中，暂不能删除",
                http_status=409,
            )
        archived = self.repository.archive_case(case_id)
        if archived is None:
            raise AppError(
                ErrorCode.EVALUATION_CASE_NOT_FOUND,
                "评测用例不存在",
                http_status=404,
            )
        return archived

    def create_run(self, payload: EvaluationRunCreate) -> dict[str, Any]:
        case_scope = payload.case_scope or (
            EvaluationCaseScope.SELECTED
            if payload.case_ids is not None
            else EvaluationCaseScope.BUILTIN_BASELINE
        )
        if case_scope is EvaluationCaseScope.BUILTIN_BASELINE:
            cases, _ = self.repository.list_cases(
                page=1,
                size=100,
                topic=None,
                expected_type=None,
                is_multi_turn=None,
                origin=EvaluationCaseOrigin.BUILTIN.value,
                status=EvaluationCaseStatus.ACTIVE.value,
                include_archived=False,
            )
        elif case_scope is EvaluationCaseScope.ALL_ACTIVE:
            cases = self.repository.get_cases()
        else:
            cases = self.repository.get_cases(payload.case_ids)
        if case_scope is EvaluationCaseScope.SELECTED and (
            payload.case_ids is None or len(cases) != len(payload.case_ids)
        ):
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                "评测用例不存在",
                http_status=400,
            )
        if not cases:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                "评测用例集为空",
                http_status=400,
            )
        snapshot = {
            "answer_style": payload.answer_style.value,
            "case_scope": case_scope.value,
            "llm_model": self.config.llm_model,
            "evaluator_model": self.config.llm_model,
            "evaluator_prompt_version": _EVALUATOR_PROMPT_VERSION,
            "embedding_provider": self.config.embedding_provider,
            "embedding_model": self.config.embedding_model,
            "embedding_normalize": self.config.embedding_normalize,
            "prompt_version": "labor_langchain_v1",
            "chunk_size": self.config.chunk_size,
            "chunk_overlap": self.config.chunk_overlap,
            "top_k": self.config.rag_top_k,
            "rerank_enabled": self.config.rerank_enabled,
            "score_threshold": self.config.rag_score_threshold,
        }
        return self.repository.create_run(
            payload.name,
            cases,
            snapshot,
        )

    def list_runs(
        self, *, page: int, size: int, status: str | None
    ) -> tuple[list[dict[str, Any]], int]:
        return self.repository.list_runs(page=page, size=size, status=status)

    def get_run(self, run_id: int) -> dict[str, Any]:
        run = self.repository.get_run(run_id)
        if run is None:
            raise AppError(
                ErrorCode.EVALUATION_RUN_NOT_FOUND,
                "评测批次不存在",
                http_status=404,
            )
        return run

    def delete_run(self, run_id: int) -> None:
        run = self.repository.delete_run(run_id)
        if run is None:
            raise AppError(
                ErrorCode.EVALUATION_RUN_NOT_FOUND,
                "评测批次不存在",
                http_status=404,
            )
        if run["status"] not in {"COMPLETED", "FAILED"}:
            raise AppError(
                ErrorCode.INVALID_EVALUATION_RUN_STATE,
                "排队中或运行中的评测批次不能删除",
                http_status=409,
            )

    async def execute_run(self, run_id: int) -> None:
        try:
            self.repository.set_run_status(run_id, "RUNNING")
            run = self.repository.get_run(run_id)
            if run is None:
                raise RuntimeError("评测批次不存在")
            answer_style = AnswerStyle(run["config"]["answer_style"])
            cases = self.repository.run_cases(run_id)
            for case in cases:
                try:
                    result = await self._evaluate_case(case, answer_style)
                except (
                    ModelUnavailableError,
                    EmbeddingUnavailableError,
                    VectorStoreNotInitialized,
                    VectorStorePersistenceError,
                    VectorStoreSignatureMismatch,
                ) as exc:
                    self.repository.add_result(
                        run_id,
                        _failed_result(case["id"], self._system_error_message(exc)),
                    )
                    self.repository.fail_run(run_id, self._system_error_message(exc))
                    return
                except Exception as exc:
                    logger.exception("Evaluation case %s failed", case["id"])
                    result = _failed_result(case["id"], str(exc) or "评测用例执行失败")
                self.repository.add_result(run_id, result)

            run = self.repository.get_run(run_id)
            if run is None:
                raise RuntimeError("评测批次在执行过程中不存在")
            result_by_case = {result["case_id"]: result for result in run["results"]}
            self.repository.complete_run(
                run_id, _calculate_metrics(cases, result_by_case)
            )
        except Exception as exc:
            logger.exception("Evaluation run %s failed", run_id)
            try:
                self.repository.fail_run(run_id, str(exc) or "评测任务失败")
            except Exception:
                logger.exception("Could not mark evaluation run %s as failed", run_id)

    async def _evaluate_case(
        self, case: dict[str, Any], answer_style: AnswerStyle
    ) -> dict[str, Any]:
        history: list[dict[str, str]] = []
        outputs: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []
        seen_chunks: set[int] = set()
        latency_ms = 0
        for question in case["turns"]:
            output = await self.chat_service.answer_once(
                question,
                history,
                answer_style,
                mode=ExecutionMode.EVALUATION,
            )
            outputs.append(output)
            history.extend(
                [
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": output["answer"]},
                ]
            )
            latency_ms += output["retrieval_ms"]
            for citation in output["citations"]:
                chunk_id = int(citation["chunk_id"])
                if chunk_id not in seen_chunks:
                    citations.append(citation)
                    seen_chunks.add(chunk_id)

        final = outputs[-1]
        refused = final["refused"]
        if case["expected_type"] == "REJECT":
            correct = refused and not final["citations"]
            multi_turn_correct = None
        else:
            judgement = await self.judge_answer(case, final)
            correct = judgement["correct"]
            multi_turn_correct = (
                correct and judgement["context_retained"]
                if len(case["turns"]) > 1
                else None
            )

        source_hit = None
        if case["expected_sources"]:
            source_hit = any(
                actual["file_name"] == expected["file_name"]
                and (
                    expected["chunk_no"] is None
                    or actual["chunk_no"] == expected["chunk_no"]
                )
                for actual in citations
                for expected in case["expected_sources"]
            )
        compliance_hit = (
            bool(final["compliance_shown"]) if case["should_show_compliance"] else None
        )
        return {
            "case_id": case["id"],
            "status": "COMPLETED",
            "answer": final["answer"],
            "refused": refused,
            "correct": correct,
            "source_hit": source_hit,
            "multi_turn_correct": multi_turn_correct,
            "compliance_hit": compliance_hit,
            "citations": citations,
            "latency_ms": latency_ms,
            "error_message": None,
        }

    async def judge_answer(
        self, case: dict[str, Any], final: dict[str, Any]
    ) -> dict[str, bool]:
        prompt_input = {
            "turns": case["turns"],
            "expected_points": case["expected_points"],
            "rewritten_question": final["rewritten_question"],
            "answer": final["answer"],
        }
        chat_model = getattr(self.chat_service, "chat_model", None)
        if chat_model is None:
            legacy_client = getattr(self.chat_service, "llm_client", None)
            if legacy_client is None:
                raise ModelUnavailableError("评测模型尚未配置")
            chat_model = ensure_chat_model(legacy_client)
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", _escape_fstring_literals(self.evaluator_prompt)),
                ("human", "{payload}"),
            ],
            template_format="f-string",
        )
        try:
            value = await (
                prompt
                | chat_model.bind(
                    response_format={"type": "json_object"},
                    temperature=0,
                )
                | JsonOutputParser()
            ).ainvoke({"payload": json.dumps(prompt_input, ensure_ascii=False)})
        except ModelUnavailableError:
            raise
        except OutputParserException as exc:
            raise TypeError("评测器未返回有效 JSON") from exc
        except Exception as exc:
            raise ModelUnavailableError("模型服务暂不可用") from exc
        if not isinstance(value, dict) or not isinstance(value.get("correct"), bool):
            raise TypeError("评测器未返回有效的 correct 判断")
        context_retained = value.get("context_retained", len(case["turns"]) == 1)
        if not isinstance(context_retained, bool):
            raise TypeError("评测器未返回有效的 context_retained 判断")
        return {"correct": value["correct"], "context_retained": context_retained}

    @staticmethod
    def _system_error_message(exc: Exception) -> str:
        if isinstance(exc, ModelUnavailableError):
            return "模型服务暂不可用，请检查模型配置与服务状态"
        if isinstance(exc, EmbeddingUnavailableError):
            return "Embedding 服务暂不可用，请检查模型配置与服务状态"
        if isinstance(exc, VectorStoreNotInitialized):
            return "知识库尚未就绪，请先导入资料并构建索引"
        if isinstance(exc, VectorStoreSignatureMismatch):
            return "向量索引与当前 Embedding 配置不兼容，请重建索引"
        if isinstance(exc, VectorStorePersistenceError):
            return "知识库索引不可用"
        return str(exc) or "评测任务失败"


def _escape_fstring_literals(value: str) -> str:
    return value.replace("{", "{{").replace("}", "}}")


def _failed_result(case_id: int, error_message: str) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "status": "FAILED",
        "answer": None,
        "refused": None,
        "correct": None,
        "source_hit": None,
        "multi_turn_correct": None,
        "compliance_hit": None,
        "citations": [],
        "latency_ms": None,
        "error_message": error_message[:500],
    }


def _calculate_metrics(
    cases: list[dict[str, Any]], results: dict[int, dict[str, Any]]
) -> dict[str, float | None]:
    def rate(successes: int, total: int) -> float | None:
        return successes / total if total else None

    completed = {
        case_id: result
        for case_id, result in results.items()
        if result["status"] == "COMPLETED"
    }
    answers = [
        case
        for case in cases
        if case["expected_type"] == "ANSWER" and case["id"] in completed
    ]
    rejects = [
        case
        for case in cases
        if case["expected_type"] == "REJECT" and case["id"] in completed
    ]
    citation_cases = [case for case in answers if case["expected_sources"]]
    multi_turn_cases = [
        case for case in cases if len(case["turns"]) > 1 and case["id"] in completed
    ]
    compliance_cases = [
        case
        for case in cases
        if case["should_show_compliance"] and case["id"] in completed
    ]
    return {
        "accuracy": rate(
            sum(completed[case["id"]]["correct"] is True for case in answers),
            len(answers),
        ),
        "reject_rate": rate(
            sum(completed[case["id"]]["correct"] is True for case in rejects),
            len(rejects),
        ),
        "citation_hit_rate": rate(
            sum(completed[case["id"]]["source_hit"] is True for case in citation_cases),
            len(citation_cases),
        ),
        "multi_turn_pass_rate": rate(
            sum(
                completed[case["id"]]["multi_turn_correct"] is True
                for case in multi_turn_cases
            ),
            len(multi_turn_cases),
        ),
        "compliance_hit_rate": rate(
            sum(
                completed[case["id"]]["compliance_hit"] is True
                for case in compliance_cases
            ),
            len(compliance_cases),
        ),
    }
