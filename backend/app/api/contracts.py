from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import StreamingResponse

from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.schemas.common import ApiResponse, PageQuery, PageResult
from app.schemas.contracts import (
    ChatRequest,
    ChunkItem,
    CreateSessionRequest,
    DocumentItem,
    DocumentQuery,
    DocumentReimportAccepted,
    DocumentUploadAccepted,
    EvaluationCase,
    EvaluationCaseQuery,
    EvaluationRunCreate,
    EvaluationRunDetail,
    EvaluationRunJob,
    EvaluationRunQuery,
    EvaluationRunSummary,
    ExperimentCreate,
    ExperimentDetail,
    ExperimentJob,
    ExperimentQuery,
    ExperimentSummary,
    MaterialChecklistInput,
    MissingKnowledgeItem,
    MissingKnowledgeQuery,
    MissingKnowledgeUpdate,
    MessageItem,
    SessionItem,
    ToolExecutionItem,
)

router = APIRouter()

_ERROR_RESPONSE = {"model": ApiResponse[None]}
CONTRACT_RESPONSES = {
    400: {**_ERROR_RESPONSE, "description": "Invalid business request"},
    404: {**_ERROR_RESPONSE, "description": "Resource not found"},
    409: {**_ERROR_RESPONSE, "description": "Resource state conflict"},
    413: {**_ERROR_RESPONSE, "description": "Uploaded file is too large"},
    422: {**_ERROR_RESPONSE, "description": "Request validation failed"},
    500: {**_ERROR_RESPONSE, "description": "Internal server error"},
    501: {**_ERROR_RESPONSE, "description": "Business implementation is scheduled for a later phase"},
    503: {**_ERROR_RESPONSE, "description": "A required service is unavailable"},
}


def _contract_only() -> NoReturn:
    raise AppError(
        code=ErrorCode.INTERNAL_ERROR,
        message="当前阶段仅冻结接口契约，业务功能将在后续阶段实现",
        http_status=501,
    )


@router.post(
    "/documents/upload",
    response_model=ApiResponse[DocumentUploadAccepted],
    status_code=202,
    responses=CONTRACT_RESPONSES,
    tags=["documents"],
    summary="Upload a document and start its import job",
)
async def upload_document(
    file: Annotated[UploadFile, File(description="PDF, DOC, DOCX or TXT document")],
) -> ApiResponse[DocumentUploadAccepted]:
    _contract_only()


@router.get(
    "/documents",
    response_model=ApiResponse[PageResult[DocumentItem]],
    responses=CONTRACT_RESPONSES,
    tags=["documents"],
    summary="List documents",
)
def list_documents(
    query: Annotated[DocumentQuery, Query()],
) -> ApiResponse[PageResult[DocumentItem]]:
    _contract_only()


@router.get(
    "/documents/{id}",
    response_model=ApiResponse[DocumentItem],
    responses=CONTRACT_RESPONSES,
    tags=["documents"],
    summary="Get a document and its import status",
)
def get_document(id: int) -> ApiResponse[DocumentItem]:
    _contract_only()


@router.post(
    "/documents/{id}/reimport",
    response_model=ApiResponse[DocumentReimportAccepted],
    status_code=202,
    responses=CONTRACT_RESPONSES,
    tags=["documents"],
    summary="Reimport a failed document",
)
def reimport_document(id: int) -> ApiResponse[DocumentReimportAccepted]:
    _contract_only()


@router.get(
    "/documents/{id}/chunks",
    response_model=ApiResponse[PageResult[ChunkItem]],
    responses=CONTRACT_RESPONSES,
    tags=["documents"],
    summary="List a document's chunks",
)
def list_document_chunks(
    id: int,
    query: Annotated[PageQuery, Query()],
) -> ApiResponse[PageResult[ChunkItem]]:
    _contract_only()


@router.post(
    "/sessions",
    response_model=ApiResponse[SessionItem],
    status_code=201,
    responses=CONTRACT_RESPONSES,
    tags=["sessions"],
    summary="Create a chat session",
)
def create_session(payload: CreateSessionRequest) -> ApiResponse[SessionItem]:
    _contract_only()


@router.get(
    "/sessions/{id}/messages",
    response_model=ApiResponse[list[MessageItem]],
    responses=CONTRACT_RESPONSES,
    tags=["sessions"],
    summary="List messages for a session",
)
def list_session_messages(id: UUID) -> ApiResponse[list[MessageItem]]:
    _contract_only()


@router.post(
    "/chat/stream",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": (
                "SSE events: optional tool, one or more token events, sources, then done; "
                "errors use a terminal error event."
            ),
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
        **CONTRACT_RESPONSES,
    },
    tags=["chat"],
    summary="Stream a RAG answer using Server-Sent Events",
)
async def stream_chat(payload: ChatRequest) -> StreamingResponse:
    _contract_only()


@router.post(
    "/tools/material-checklist",
    response_model=ApiResponse[ToolExecutionItem],
    responses=CONTRACT_RESPONSES,
    tags=["tools"],
    summary="Generate a material checklist",
)
def material_checklist(payload: MaterialChecklistInput) -> ApiResponse[ToolExecutionItem]:
    _contract_only()


@router.get(
    "/evaluations/cases",
    response_model=ApiResponse[PageResult[EvaluationCase]],
    responses=CONTRACT_RESPONSES,
    tags=["evaluations"],
    summary="List evaluation cases",
)
def list_evaluation_cases(
    query: Annotated[EvaluationCaseQuery, Query()],
) -> ApiResponse[PageResult[EvaluationCase]]:
    _contract_only()


@router.post(
    "/evaluations/runs",
    response_model=ApiResponse[EvaluationRunJob],
    status_code=202,
    responses=CONTRACT_RESPONSES,
    tags=["evaluations"],
    summary="Create an evaluation run",
)
def create_evaluation_run(payload: EvaluationRunCreate) -> ApiResponse[EvaluationRunJob]:
    _contract_only()


@router.get(
    "/evaluations/runs",
    response_model=ApiResponse[PageResult[EvaluationRunSummary]],
    responses=CONTRACT_RESPONSES,
    tags=["evaluations"],
    summary="List evaluation runs",
)
def list_evaluation_runs(
    query: Annotated[EvaluationRunQuery, Query()],
) -> ApiResponse[PageResult[EvaluationRunSummary]]:
    _contract_only()


@router.get(
    "/evaluations/runs/{id}",
    response_model=ApiResponse[EvaluationRunDetail],
    responses=CONTRACT_RESPONSES,
    tags=["evaluations"],
    summary="Get an evaluation run",
)
def get_evaluation_run(id: int) -> ApiResponse[EvaluationRunDetail]:
    _contract_only()


@router.get(
    "/missing-knowledge",
    response_model=ApiResponse[PageResult[MissingKnowledgeItem]],
    responses=CONTRACT_RESPONSES,
    tags=["missing-knowledge"],
    summary="List missing-knowledge topics",
)
def list_missing_knowledge(
    query: Annotated[MissingKnowledgeQuery, Query()],
) -> ApiResponse[PageResult[MissingKnowledgeItem]]:
    _contract_only()


@router.patch(
    "/missing-knowledge/{id}",
    response_model=ApiResponse[MissingKnowledgeItem],
    responses=CONTRACT_RESPONSES,
    tags=["missing-knowledge"],
    summary="Update a missing-knowledge topic",
)
def update_missing_knowledge(
    id: int, payload: MissingKnowledgeUpdate
) -> ApiResponse[MissingKnowledgeItem]:
    _contract_only()


@router.get(
    "/retrieval-experiments",
    response_model=ApiResponse[PageResult[ExperimentSummary]],
    responses=CONTRACT_RESPONSES,
    tags=["retrieval-experiments"],
    summary="List retrieval experiments",
)
def list_experiments(
    query: Annotated[ExperimentQuery, Query()],
) -> ApiResponse[PageResult[ExperimentSummary]]:
    _contract_only()


@router.post(
    "/retrieval-experiments",
    response_model=ApiResponse[ExperimentJob],
    status_code=202,
    responses=CONTRACT_RESPONSES,
    tags=["retrieval-experiments"],
    summary="Create a retrieval experiment",
)
def create_experiment(payload: ExperimentCreate) -> ApiResponse[ExperimentJob]:
    _contract_only()


@router.get(
    "/retrieval-experiments/{id}",
    response_model=ApiResponse[ExperimentDetail],
    responses=CONTRACT_RESPONSES,
    tags=["retrieval-experiments"],
    summary="Get a retrieval experiment",
)
def get_experiment(id: int) -> ApiResponse[ExperimentDetail]:
    _contract_only()
