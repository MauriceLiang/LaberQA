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


class EvaluationCaseOrigin(StrEnum):
    BUILTIN = "BUILTIN"
    CUSTOM = "CUSTOM"


class EvaluationCaseStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class EvaluationCaseScope(StrEnum):
    BUILTIN_BASELINE = "BUILTIN_BASELINE"
    ALL_ACTIVE = "ALL_ACTIVE"
    SELECTED = "SELECTED"


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
    file_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ]
    chunk_no: int | None = Field(default=None, ge=1)


EvaluationTurn = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]
EvaluationPoint = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]


class EvaluationCasePayload(ApiModel):
    topic: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)
    ]
    expected_type: EvaluationExpectedType
    turns: list[EvaluationTurn] = Field(min_length=1, max_length=10)
    expected_points: list[EvaluationPoint] = Field(default_factory=list, max_length=20)
    expected_sources: list[ExpectedSource] = Field(default_factory=list, max_length=20)
    should_show_compliance: bool = False

    @model_validator(mode="after")
    def validate_expected_points(self) -> "EvaluationCasePayload":
        if self.expected_type is EvaluationExpectedType.ANSWER and not self.expected_points:
            raise ValueError("ANSWER cases require at least one expected point")
        return self


class EvaluationCaseCreate(EvaluationCasePayload):
    pass


class EvaluationCaseUpdate(EvaluationCasePayload):
    version: int = Field(ge=1)


class EvaluationCase(EvaluationCasePayload):
    id: int
    origin: EvaluationCaseOrigin
    status: EvaluationCaseStatus
    version: int = Field(ge=1)
    created_at: UtcDateTime
    updated_at: UtcDateTime
    archived_at: UtcDateTime | None = None


class EvaluationCaseQuery(PageQuery):
    topic: str | None = None
    expected_type: EvaluationExpectedType | None = None
    is_multi_turn: bool | None = None
    origin: EvaluationCaseOrigin | None = None
    status: EvaluationCaseStatus | None = None
    include_archived: bool = False


class EvaluationRunCreate(ApiModel):
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
    case_ids: list[int] | None = Field(default=None, min_length=1)
    answer_style: AnswerStyle
    case_scope: EvaluationCaseScope | None = None

    @model_validator(mode="after")
    def unique_case_ids(self) -> "EvaluationRunCreate":
        if self.case_ids is not None and len(set(self.case_ids)) != len(self.case_ids):
            raise ValueError("case_ids must not contain duplicates")
        if self.case_scope is None:
            self.case_scope = (
                EvaluationCaseScope.SELECTED
                if self.case_ids is not None
                else EvaluationCaseScope.BUILTIN_BASELINE
            )
        elif self.case_scope is EvaluationCaseScope.SELECTED and not self.case_ids:
            raise ValueError("SELECTED runs require case_ids")
        elif self.case_scope is not EvaluationCaseScope.SELECTED and self.case_ids is not None:
            raise ValueError("case_ids is only valid for SELECTED runs")
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
    case_scope: EvaluationCaseScope | None = None
    llm_model: str
    evaluator_model: str
    evaluator_prompt_version: str
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
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
    case_ids: list[int] | None = Field(default=None, min_length=1)
    answer_style: AnswerStyle
    configs: list[ExperimentConfig] = Field(min_length=1)
    case_scope: EvaluationCaseScope | None = None
    config_names: list[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    ] | None = None

    @model_validator(mode="after")
    def unique_case_ids(self) -> "ExperimentCreate":
        if self.case_ids is not None and len(set(self.case_ids)) != len(self.case_ids):
            raise ValueError("case_ids must not contain duplicates")
        if self.case_scope is None:
            self.case_scope = (
                EvaluationCaseScope.SELECTED
                if self.case_ids is not None
                else EvaluationCaseScope.BUILTIN_BASELINE
            )
        elif self.case_scope is EvaluationCaseScope.SELECTED and not self.case_ids:
            raise ValueError("SELECTED experiments require case_ids")
        elif self.case_scope is not EvaluationCaseScope.SELECTED and self.case_ids is not None:
            raise ValueError("case_ids is only valid for SELECTED experiments")
        if self.config_names is not None and len(self.config_names) != len(self.configs):
            raise ValueError("config_names must match configs")
        return self


class ExperimentCopy(ApiModel):
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]


class ExperimentJob(JobProgress):
    experiment_id: int


class ExperimentQuery(PageQuery):
    status: JobStatus | None = None
    include_archived: bool = False


class ExperimentSummary(JobProgress):
    id: int
    name: str
    created_at: UtcDateTime
    updated_at: UtcDateTime
    archived_at: UtcDateTime | None = None


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
    archived_at: UtcDateTime | None = None
    best_config_index: int | None
    config_names: list[str] = Field(default_factory=list)
    config_results: list[ExperimentConfigResult]
    results: list[ExperimentCaseResult]


class RetrievalStrategy(ApiModel):
    id: int
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
    description: str
    builtin_key: str | None
    config: ExperimentConfig
    is_builtin: bool
    version: int = Field(ge=1)
    is_active: bool
    archived_at: UtcDateTime | None
    created_at: UtcDateTime
    updated_at: UtcDateTime


class RetrievalStrategyCreate(ApiModel):
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] = ""
    config: ExperimentConfig


class RetrievalStrategyUpdate(RetrievalStrategyCreate):
    pass


class RetrievalStrategyStatusUpdate(ApiModel):
    is_active: bool


class RetrievalStrategyVersion(ApiModel):
    id: int
    strategy_id: int
    version: int = Field(ge=1)
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
    description: str
    config: ExperimentConfig
    created_at: UtcDateTime


class RetrievalPreviewRequest(ApiModel):
    question: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
    ]
    answer_style: AnswerStyle
    config: ExperimentConfig


class RetrievalTraceStage(ApiModel):
    stage: str
    status: Literal["completed", "skipped", "failed"]
    detail: str
    duration_ms: int | None = Field(default=None, ge=0)


class RetrievalPreviewResponse(ApiModel):
    question: str
    rewritten_question: str
    answer: str
    refused: bool
    retrieval_ms: int = Field(ge=0)
    retrieved_sources: list[CitationItem]
    citations: list[CitationItem]
    trace: list[RetrievalTraceStage]
    config: ExperimentConfig


class IndexMeta(EmbeddingSignature):
    chunk_size: int = Field(ge=1)
    chunk_overlap: int = Field(ge=0)
    created_at: UtcDateTime
