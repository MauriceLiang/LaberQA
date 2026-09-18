"""Isolated asynchronous experiments for comparing retrieval configurations."""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import Settings, settings
from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.repositories.document_repository import DocumentRepository
from app.repositories.evaluation_repository import EvaluationRepository
from app.repositories.retrieval_experiment_repository import (
    RetrievalExperimentRepository,
)
from app.schemas.contracts import (
    AnswerStyle,
    EmbeddingSignature,
    ExperimentConfig,
    ExperimentCreate,
)
from app.services.chat_service import ChatService
from app.services.document_parser import ParserFactory
from app.services.embedding import (
    EmbeddingDimensionUnknown,
    EmbeddingService,
    EmbeddingUnavailableError,
)
from app.services.evaluation_service import EvaluationService
from app.services.file_storage import DocumentConverterUnavailable, DocumentParseError
from app.services.llm import ModelUnavailableError
from app.services.missing_knowledge import ExecutionMode
from app.services.rerank import RerankService
from app.services.retrieval import RetrievalService
from app.services.text import TextChunker
from app.services.vector_store import (
    VectorStoreNotInitialized,
    VectorStorePersistenceError,
    VectorStoreService,
    VectorStoreSignatureMismatch,
)

logger = logging.getLogger(__name__)
_RESTART_ERROR = "服务重启导致任务中断"


class _ExperimentChunkRepository:
    """Expose this profile's chunks to RetrievalService without touching SQLite."""

    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self.chunks = chunks

    def list_success_chunks(self) -> list[dict[str, Any]]:
        return self.chunks


class RetrievalExperimentService:
    def __init__(
        self,
        chat_service: ChatService,
        config: Settings = settings,
        *,
        document_repository: DocumentRepository | None = None,
        evaluation_repository: EvaluationRepository | None = None,
        repository: RetrievalExperimentRepository | None = None,
        embedding_service: EmbeddingService | None = None,
        parser: type[ParserFactory] = ParserFactory,
        evaluation_service: EvaluationService | None = None,
    ) -> None:
        self.chat_service = chat_service
        self.config = config
        self.document_repository = document_repository or DocumentRepository(
            config.database_path
        )
        self.evaluation_service = evaluation_service or EvaluationService(
            chat_service,
            config,
            repository=evaluation_repository,
        )
        self.repository = repository or RetrievalExperimentRepository(
            config.database_path
        )
        self.embedding_service = embedding_service or (
            chat_service.retrieval_service.embedding_service
        )
        self.production_vector_store = chat_service.retrieval_service.vector_store
        self.parser = parser

    def initialize(self) -> None:
        self.repository.recover_interrupted_experiments()

    def create_experiment(self, payload: ExperimentCreate) -> dict[str, Any]:
        cases = self.evaluation_service.repository.get_cases(payload.case_ids)
        if payload.case_ids is not None and len(cases) != len(payload.case_ids):
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                "评测用例不存在",
                http_status=400,
            )
        if not cases:
            raise AppError(ErrorCode.INVALID_REQUEST, "实验用例集为空", 400)
        if not self.document_repository.list_success_documents():
            raise AppError(
                ErrorCode.KNOWLEDGE_BASE_NOT_READY,
                "没有可用于检索实验的成功资料",
                http_status=503,
            )

        signature = self._embedding_signature()
        snapshot = {
            "answer_style": payload.answer_style.value,
            "case_ids": [case["id"] for case in cases],
            "case_snapshots": [
                {
                    "id": case["id"],
                    "version": case.get("version", 1),
                    "topic": case["topic"],
                    "expected_type": case["expected_type"],
                    "turns": case["turns"],
                    "expected_points": case["expected_points"],
                    "expected_sources": case["expected_sources"],
                    "should_show_compliance": case["should_show_compliance"],
                }
                for case in cases
            ],
            "configs": [config.model_dump(mode="json") for config in payload.configs],
            "embedding_signature": signature.model_dump(mode="json"),
        }
        return self.repository.create_experiment(
            payload.name,
            len(cases),
            snapshot,
        )

    def list_experiments(
        self, *, page: int, size: int, status: str | None
    ) -> tuple[list[dict[str, Any]], int]:
        return self.repository.list_experiments(page=page, size=size, status=status)

    def get_experiment(self, experiment_id: int) -> dict[str, Any]:
        experiment = self.repository.get_experiment(experiment_id)
        if experiment is None:
            raise AppError(
                ErrorCode.EXPERIMENT_NOT_FOUND,
                "检索实验不存在",
                http_status=404,
            )
        cases = _snapshot_cases(
            experiment["snapshot"], self.evaluation_service.repository
        )
        config_results = _calculate_config_results(
            cases,
            experiment["snapshot"]["configs"],
            experiment["results"],
        )
        return {
            **experiment,
            "embedding_signature": experiment["snapshot"]["embedding_signature"],
            "config_results": config_results,
        }

    async def execute_experiment(self, experiment_id: int) -> None:
        try:
            self.repository.set_running(experiment_id)
            experiment = self.repository.get_experiment(experiment_id)
            if experiment is None:
                raise RuntimeError("检索实验不存在")
            snapshot = experiment["snapshot"]
            cases = _snapshot_cases(snapshot, self.evaluation_service.repository)
            signature = EmbeddingSignature.model_validate(
                snapshot["embedding_signature"]
            )
            profiles: dict[
                tuple[int, int], tuple[list[dict[str, Any]], VectorStoreService]
            ] = {}

            for config_index, config_data in enumerate(snapshot["configs"]):
                config = ExperimentConfig.model_validate(config_data)
                profile_key = (config.chunk_size, config.chunk_overlap)
                if profile_key not in profiles:
                    profiles[profile_key] = self._build_profile(
                        experiment_id, config, signature
                    )
                chunks, vector_store = profiles[profile_key]
                variant_chat = self._build_chat_service(config, chunks, vector_store)

                for case in cases:
                    try:
                        result = await self._evaluate_case(
                            variant_chat,
                            case,
                            config_index,
                            AnswerStyle(snapshot["answer_style"]),
                        )
                    except (
                        ModelUnavailableError,
                        EmbeddingUnavailableError,
                        EmbeddingDimensionUnknown,
                        VectorStoreNotInitialized,
                        VectorStorePersistenceError,
                        VectorStoreSignatureMismatch,
                    ) as exc:
                        self.repository.add_result(
                            experiment_id,
                            _failed_result(
                                config_index,
                                case["id"],
                                self._system_error_message(exc),
                            ),
                        )
                        self.repository.fail_experiment(
                            experiment_id, self._system_error_message(exc)
                        )
                        return
                    except Exception as exc:
                        logger.exception(
                            "Experiment %s config %s case %s failed",
                            experiment_id,
                            config_index,
                            case["id"],
                        )
                        result = _failed_result(
                            config_index,
                            case["id"],
                            str(exc) or "检索实验用例执行失败",
                        )
                    self.repository.add_result(experiment_id, result)

            detail = self.repository.get_experiment(experiment_id)
            if detail is None:
                raise RuntimeError("检索实验在执行过程中不存在")
            config_results = _calculate_config_results(
                cases,
                snapshot["configs"],
                detail["results"],
            )
            best = _best_config(config_results, detail["results"])
            best_metrics = config_results[best] if best is not None else None
            self.repository.complete_experiment(
                experiment_id,
                best,
                best_metrics,
            )
        except Exception as exc:
            logger.exception("Retrieval experiment %s failed", experiment_id)
            try:
                self.repository.fail_experiment(
                    experiment_id, self._system_error_message(exc)
                )
            except Exception:
                logger.exception(
                    "Could not mark retrieval experiment %s as failed", experiment_id
                )

    def _embedding_signature(self) -> EmbeddingSignature:
        profile = self.production_vector_store.meta
        dimension = None
        if profile is not None:
            provider_matches = (
                profile.embedding_provider == self.config.embedding_provider
                and profile.embedding_model == self.config.embedding_model
                and profile.normalize_embeddings == self.config.embedding_normalize
            )
            if provider_matches:
                dimension = profile.embedding_dimension
        try:
            return self.embedding_service.signature(dimension)
        except (EmbeddingDimensionUnknown, EmbeddingUnavailableError) as exc:
            raise AppError(
                ErrorCode.EMBEDDING_UNAVAILABLE,
                "无法确定当前 Embedding 签名，请先成功导入一份资料",
                http_status=503,
            ) from exc

    def _build_profile(
        self,
        experiment_id: int,
        config: ExperimentConfig,
        signature: EmbeddingSignature,
    ) -> tuple[list[dict[str, Any]], VectorStoreService]:
        chunks = self._chunk_success_documents(config)
        if not chunks:
            raise ValueError("成功资料未生成可检索的 Chunk")

        vectors: list[list[float]] = []
        batch_size = self.config.embedding_batch_size
        texts = [chunk["content"] for chunk in chunks]
        for start in range(0, len(texts), batch_size):
            batch = self.embedding_service.embed_documents(
                texts[start : start + batch_size]
            )
            if len(batch) != len(texts[start : start + batch_size]):
                raise EmbeddingUnavailableError("Embedding 返回数量与 Chunk 不一致")
            vectors.extend(batch)

        actual_signature = self.embedding_service.signature(len(vectors[0]))
        if actual_signature != signature:
            raise VectorStoreSignatureMismatch("实验 Embedding 签名在执行期间发生变化")

        runtime_config = _runtime_config(self.config, config)
        index_dir = (
            self.config.faiss_path
            / "experiments"
            / f"experiment_{experiment_id}"
            / f"chunk_{config.chunk_size}_overlap_{config.chunk_overlap}"
        )
        vector_store = VectorStoreService(
            config=runtime_config,
            embedding_service=self.embedding_service,
            index_dir=index_dir,
        )
        vector_store.rebuild_from_success_chunks(
            [
                (chunk["id"], vector)
                for chunk, vector in zip(chunks, vectors, strict=True)
            ],
            signature,
        )
        return chunks, vector_store

    def _chunk_success_documents(
        self, config: ExperimentConfig
    ) -> list[dict[str, Any]]:
        chunker = TextChunker(config.chunk_size, config.chunk_overlap)
        chunks: list[dict[str, Any]] = []
        for document in self.document_repository.list_success_documents():
            source_text = self.parser.parse(
                document["file_path"], document["file_type"]
            )
            for chunk in chunker.chunk(source_text):
                chunks.append(
                    {
                        "id": len(chunks) + 1,
                        "document_id": int(document["id"]),
                        "file_name": str(document["file_name"]),
                        "chunk_no": chunk.chunk_no,
                        "content": chunk.content,
                    }
                )
        return chunks

    def _build_chat_service(
        self,
        config: ExperimentConfig,
        chunks: list[dict[str, Any]],
        vector_store: VectorStoreService,
    ) -> ChatService:
        runtime_config = _runtime_config(self.config, config)
        retrieval_service = RetrievalService(
            runtime_config,
            repository=_ExperimentChunkRepository(chunks),  # type: ignore[arg-type]
            embedding_service=self.embedding_service,
            vector_store=vector_store,
            rerank_service=RerankService(runtime_config),
        )
        return ChatService(
            self.chat_service.session_service,
            retrieval_service,
            runtime_config,
            llm_client=self.chat_service.llm_client,
            missing_knowledge_service=self.chat_service.missing_knowledge_service,
        )

    async def _evaluate_case(
        self,
        chat_service: ChatService,
        case: dict[str, Any],
        config_index: int,
        answer_style: AnswerStyle,
    ) -> dict[str, Any]:
        history: list[dict[str, str]] = []
        outputs: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []
        seen_chunks: set[int] = set()
        retrieval_ms = 0
        for question in case["turns"]:
            output = await chat_service.answer_once(
                question,
                history,
                answer_style,
                mode=ExecutionMode.EXPERIMENT,
            )
            outputs.append(output)
            history.extend(
                [
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": output["answer"]},
                ]
            )
            retrieval_ms += output["retrieval_ms"]
            for citation in output["citations"]:
                chunk_id = int(citation["chunk_id"])
                if chunk_id not in seen_chunks:
                    citations.append(citation)
                    seen_chunks.add(chunk_id)

        final = outputs[-1]
        refused = bool(final["refused"])
        if case["expected_type"] == "REJECT":
            correct = refused and not citations
        else:
            judgement = await self.evaluation_service.judge_answer(case, final)
            correct = judgement["correct"]

        source_hit = None
        if case["expected_sources"]:
            # Rechunking changes chunk_no; compare source documents across profiles.
            source_hit = any(
                actual["file_name"] == expected["file_name"]
                for actual in citations
                for expected in case["expected_sources"]
            )
        return {
            "config_index": config_index,
            "case_id": case["id"],
            "status": "COMPLETED",
            "retrieved_sources": citations,
            "source_hit": source_hit,
            "correct": correct,
            "refused": refused,
            "retrieval_ms": retrieval_ms,
            "error_message": None,
        }

    @staticmethod
    def _system_error_message(exc: Exception) -> str:
        if isinstance(exc, ModelUnavailableError):
            return "模型服务暂不可用，请检查模型配置与服务状态"
        if isinstance(exc, (EmbeddingUnavailableError, EmbeddingDimensionUnknown)):
            return "Embedding 服务暂不可用，请检查模型配置与服务状态"
        if isinstance(exc, VectorStoreNotInitialized):
            return "实验向量索引尚未初始化"
        if isinstance(exc, VectorStoreSignatureMismatch):
            return "实验 Embedding 签名不一致，请检查 Embedding 配置"
        if isinstance(exc, VectorStorePersistenceError):
            return "实验向量索引不可用"
        if isinstance(exc, DocumentConverterUnavailable):
            return "实验无法解析 DOC 资料，请检查 LibreOffice 配置"
        if isinstance(exc, DocumentParseError):
            return "实验无法解析成功资料，请检查原始文件"
        return str(exc)[:500] or "检索实验失败"


def _runtime_config(config: Settings, experiment: ExperimentConfig) -> Settings:
    return config.model_copy(
        update={
            "chunk_size": experiment.chunk_size,
            "chunk_overlap": experiment.chunk_overlap,
            "rag_top_k": experiment.top_k,
            "rerank_enabled": experiment.rerank_enabled,
            "rerank_top_n": experiment.rerank_top_n,
            "rag_score_threshold": experiment.score_threshold,
        }
    )


def _failed_result(config_index: int, case_id: int, message: str) -> dict[str, Any]:
    return {
        "config_index": config_index,
        "case_id": case_id,
        "status": "FAILED",
        "retrieved_sources": [],
        "source_hit": None,
        "correct": None,
        "refused": None,
        "retrieval_ms": None,
        "error_message": message[:500],
    }


def _snapshot_cases(
    snapshot: dict[str, Any], repository: Any
) -> list[dict[str, Any]]:
    case_snapshots = snapshot.get("case_snapshots")
    if isinstance(case_snapshots, list) and case_snapshots:
        return case_snapshots
    return repository.get_cases(
        snapshot.get("case_ids"), include_archived=True
    )


def _calculate_config_results(
    cases: list[dict[str, Any]],
    configs: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    results_by_config: dict[int, list[dict[str, Any]]] = {}
    for result in results:
        results_by_config.setdefault(result["config_index"], []).append(result)

    summaries: list[dict[str, Any]] = []
    for config_index, config in enumerate(configs):
        result_by_case = {
            result["case_id"]: result
            for result in results_by_config.get(config_index, [])
        }
        completed = {
            case_id: result
            for case_id, result in result_by_case.items()
            if result["status"] == "COMPLETED"
        }
        processed_cases = [case for case in cases if case["id"] in result_by_case]
        answer_cases = [
            case for case in processed_cases if case["expected_type"] == "ANSWER"
        ]
        reject_cases = [
            case for case in processed_cases if case["expected_type"] == "REJECT"
        ]
        citation_cases = [case for case in answer_cases if case["expected_sources"]]
        times = [
            result["retrieval_ms"]
            for result in completed.values()
            if result["retrieval_ms"] is not None
        ]
        summaries.append(
            {
                "config_index": config_index,
                "config": config,
                "accuracy": _rate(
                    sum(
                        completed.get(case["id"], {}).get("correct") is True
                        for case in answer_cases
                    ),
                    len(answer_cases),
                ),
                "reject_rate": _rate(
                    sum(
                        completed.get(case["id"], {}).get("correct") is True
                        for case in reject_cases
                    ),
                    len(reject_cases),
                ),
                "citation_hit_rate": _rate(
                    sum(
                        completed.get(case["id"], {}).get("source_hit") is True
                        for case in citation_cases
                    ),
                    len(citation_cases),
                ),
                "avg_retrieval_ms": sum(times) / len(times) if times else None,
            }
        )
    return summaries


def _rate(successes: int, total: int) -> float | None:
    return successes / total if total else None


def _best_config(
    config_results: list[dict[str, Any]], results: list[dict[str, Any]]
) -> int | None:
    completed_by_config = {
        result["config_index"] for result in results if result["status"] == "COMPLETED"
    }
    if not completed_by_config:
        return None

    def sort_key(item: dict[str, Any]) -> tuple[float, float, float, float, int]:
        return (
            -(
                item["citation_hit_rate"]
                if item["citation_hit_rate"] is not None
                else -1
            ),
            -(item["accuracy"] if item["accuracy"] is not None else -1),
            -(item["reject_rate"] if item["reject_rate"] is not None else -1),
            item["avg_retrieval_ms"]
            if item["avg_retrieval_ms"] is not None
            else float("inf"),
            item["config_index"],
        )

    return min(
        (
            item
            for item in config_results
            if item["config_index"] in completed_by_config
        ),
        key=sort_key,
    )["config_index"]
