from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from app.schemas.common import ApiModel, PageQuery, UtcDateTime

Score = Annotated[float, Field(ge=0, le=1)]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class FileType(StrEnum):
    PDF = "pdf"
    DOC = "doc"
    DOCX = "docx"
    TXT = "txt"


class DocumentStatus(StrEnum):
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AnswerStyle(StrEnum):
    PLAIN = "plain"
    LEGAL = "legal"


class MissingKnowledgeStatus(StrEnum):
    PENDING = "PENDING"
    RESOLVED = "RESOLVED"
    IGNORED = "IGNORED"


class EvaluationExpectedType(StrEnum):
    ANSWER = "ANSWER"
    REJECT = "REJECT"


class DocumentItem(ApiModel):
    id: int
    file_name: str
    file_type: FileType
    status: DocumentStatus
    chunk_count: int
    error_message: str | None
    created_at: UtcDateTime
    updated_at: UtcDateTime


class DocumentUploadAccepted(ApiModel):
    document_id: int
    file_name: str
    status: DocumentStatus


class DocumentReimportAccepted(ApiModel):
    document_id: int
    status: DocumentStatus


class DocumentQuery(PageQuery):
    status: DocumentStatus | None = None
    keyword: str | None = None


class ChunkItem(ApiModel):
    id: int
    document_id: int
    chunk_no: int
    content: str
    vector_key: str


class SessionItem(ApiModel):
    id: UUID
    title: str | None
    created_at: UtcDateTime
    updated_at: UtcDateTime


class CreateSessionRequest(ApiModel):
    title: str | None = Field(default=None, max_length=100)


class CitationItem(ApiModel):
    chunk_id: int
    document_id: int
    file_name: str
    chunk_no: int
    content: str
    score: Score
    retrieval_score: Score
    rerank_score: Score | None
    rank_no: int


class MaterialChecklistInput(ApiModel):
    dispute_type: NonEmptyText
    description: NonEmptyText


class MaterialChecklistOutput(ApiModel):
    materials: list[str]
    note: str


class ToolExecutionItem(ApiModel):
    tool_name: Literal["generate_rights_material_checklist"]
    input: MaterialChecklistInput
    output: MaterialChecklistOutput


class MessageItem(ApiModel):
    id: int
    session_id: UUID
    role: Literal["user", "assistant"]
    content: str
    rewritten_question: str | None
    answer_style: AnswerStyle | None
    refused: bool | None
    created_at: UtcDateTime
    citations: list[CitationItem]
    tool_executions: list[ToolExecutionItem]


class JobProgress(ApiModel):
    status: JobStatus
    progress_current: int = Field(ge=0)
    progress_total: int = Field(ge=0)
    error_message: str | None


class ChatRequest(ApiModel):
    session_id: UUID
    question: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
    ]
    answer_style: AnswerStyle


class ExpectedSource(ApiModel):
    file_name: str
    chunk_no: int | None


class EvaluationCase(ApiModel):
    id: int
    topic: str
    expected_type: EvaluationExpectedType
    turns: list[str]
    expected_points: list[str]
    expected_sources: list[ExpectedSource]
    should_show_compliance: bool


class EvaluationCaseQuery(PageQuery):
    topic: str | None = None
    expected_type: EvaluationExpectedType | None = None
    is_multi_turn: bool | None = None


class EvaluationRunCreate(ApiModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    case_ids: list[int] | None = Field(default=None, min_length=1)
    answer_style: AnswerStyle

    @model_validator(mode="after")
    def unique_case_ids(self) -> "EvaluationRunCreate":
        if self.case_ids is not None and len(set(self.case_ids)) != len(self.case_ids):
            raise ValueError("case_ids must not contain duplicates")
        return self


class EvaluationRunJob(JobProgress):
    run_id: int


class EvaluationRunQuery(PageQuery):
    status: JobStatus | None = None


class EvaluationRunSummary(JobProgress):
    id: int
    name: str
    created_at: UtcDateTime
    updated_at: UtcDateTime


class EvaluationRunConfig(ApiModel):
    answer_style: AnswerStyle
    llm_model: str
    embedding_provider: Literal["local", "api"]
    embedding_model: str
    embedding_normalize: bool
    prompt_version: str
    chunk_size: int
    chunk_overlap: int
    top_k: int
    rerank_enabled: bool
    score_threshold: Score


class EvaluationResultItem(ApiModel):
    case_id: int
    status: Literal["COMPLETED", "FAILED"]
    answer: str | None
    refused: bool | None
    correct: bool | None
    source_hit: bool | None
    multi_turn_correct: bool | None
    compliance_hit: bool | None
    citations: list[CitationItem]
    latency_ms: int | None
    error_message: str | None


class EvaluationMetrics(ApiModel):
    accuracy: Score | None
    reject_rate: Score | None
    citation_hit_rate: Score | None
    multi_turn_pass_rate: Score | None
    compliance_hit_rate: Score | None


class EvaluationRunDetail(JobProgress):
    id: int
    name: str
    config: EvaluationRunConfig
    metrics: EvaluationMetrics | None
    results: list[EvaluationResultItem]


class MissingKnowledgeItem(ApiModel):
    id: int
    topic_key: str
    sample_question: str
    count: int
    missing_area: str
    status: MissingKnowledgeStatus
    note: str | None
    first_seen_at: UtcDateTime
    last_seen_at: UtcDateTime


class MissingKnowledgeQuery(PageQuery):
    status: MissingKnowledgeStatus | None = None
    keyword: str | None = None
    sort: Literal["count_desc", "last_seen_desc"] = "count_desc"


class MissingKnowledgeUpdate(ApiModel):
    status: MissingKnowledgeStatus
    note: str | None = None


class ExperimentConfig(ApiModel):
    chunk_size: int = Field(ge=100, le=2000)
    chunk_overlap: int = Field(ge=0, le=500)
    top_k: int = Field(ge=1, le=20)
    rerank_enabled: bool
    rerank_top_n: int = Field(ge=1)
    score_threshold: Score

    @model_validator(mode="after")
    def validate_relationships(self) -> "ExperimentConfig":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")
        if self.rerank_top_n > self.top_k:
            raise ValueError("rerank_top_n must be less than or equal to top_k")
        return self


class ExperimentCreate(ApiModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    case_ids: list[int] | None = Field(default=None, min_length=1)
    answer_style: AnswerStyle
    configs: list[ExperimentConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_case_ids(self) -> "ExperimentCreate":
        if self.case_ids is not None and len(set(self.case_ids)) != len(self.case_ids):
            raise ValueError("case_ids must not contain duplicates")
        return self


class ExperimentJob(JobProgress):
    experiment_id: int


class ExperimentQuery(PageQuery):
    status: JobStatus | None = None


class ExperimentSummary(JobProgress):
    id: int
    name: str
    created_at: UtcDateTime
    updated_at: UtcDateTime


class ExperimentConfigResult(ApiModel):
    config_index: int
    config: ExperimentConfig
    accuracy: Score | None
    reject_rate: Score | None
    citation_hit_rate: Score | None
    avg_retrieval_ms: float | None


class ExperimentCaseResult(ApiModel):
    config_index: int
    case_id: int
    status: Literal["COMPLETED", "FAILED"]
    retrieved_sources: list[CitationItem]
    source_hit: bool | None
    correct: bool | None
    refused: bool | None
    retrieval_ms: int | None
    error_message: str | None


class EmbeddingSignature(ApiModel):
    embedding_provider: Literal["local", "api"]
    embedding_model: str
    embedding_dimension: int = Field(ge=1)
    normalize_embeddings: bool


class ExperimentDetail(JobProgress):
    id: int
    name: str
    embedding_signature: EmbeddingSignature
    best_config_index: int | None
    config_results: list[ExperimentConfigResult]
    results: list[ExperimentCaseResult]


class IndexMeta(EmbeddingSignature):
    chunk_size: int = Field(ge=1)
    chunk_overlap: int = Field(ge=0)
    created_at: UtcDateTime
