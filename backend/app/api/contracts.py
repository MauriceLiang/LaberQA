from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_chat_service, get_document_service
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
    MessageItem,
    MissingKnowledgeItem,
    MissingKnowledgeQuery,
    MissingKnowledgeUpdate,
    SessionItem,
    ToolExecutionItem,
)
from app.services.chat_service import ChatService
from app.services.document_service import DocumentService

router = APIRouter()

_ERROR_RESPONSE = {"model": ApiResponse[None]}
CONTRACT_RESPONSES = {
    400: {**_ERROR_RESPONSE, "description": "Invalid business request"},
    404: {**_ERROR_RESPONSE, "description": "Resource not found"},
    409: {**_ERROR_RESPONSE, "description": "Resource state conflict"},
    413: {**_ERROR_RESPONSE, "description": "Uploaded file is too large"},
    422: {**_ERROR_RESPONSE, "description": "Request validation failed"},
    500: {**_ERROR_RESPONSE, "description": "Internal server error"},
    501: {
        **_ERROR_RESPONSE,
        "description": "Business implementation is scheduled for a later phase",
    },
    503: {**_ERROR_RESPONSE, "description": "A required service is unavailable"},
}
IMPLEMENTED_RESPONSES = {
    status: response for status, response in CONTRACT_RESPONSES.items() if status != 501
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
    background_tasks: BackgroundTasks,
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> ApiResponse[DocumentUploadAccepted]:
    document = service.upload(file.file, file.filename, file.content_type)
    background_tasks.add_task(service.import_document, document["id"])
    return ApiResponse(
        code=0,
        message="accepted",
        data=DocumentUploadAccepted(
            document_id=document["id"],
            file_name=document["file_name"],
            status=document["status"],
        ),
    )


@router.get(
    "/documents",
    response_model=ApiResponse[PageResult[DocumentItem]],
    responses=CONTRACT_RESPONSES,
    tags=["documents"],
    summary="List documents",
)
def list_documents(
    query: Annotated[DocumentQuery, Query()],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> ApiResponse[PageResult[DocumentItem]]:
    items, total = service.repository.list_documents(
        page=query.page,
        size=query.size,
        status=query.status.value if query.status else None,
        keyword=query.keyword,
    )
    return ApiResponse(
        code=0,
        message="success",
        data=PageResult(
            items=[
                DocumentItem.model_validate(_schema_fields(DocumentItem, item))
                for item in items
            ],
            page=query.page,
            size=query.size,
            total=total,
            pages=(total + query.size - 1) // query.size,
        ),
    )


@router.get(
    "/documents/{id}",
    response_model=ApiResponse[DocumentItem],
    responses=CONTRACT_RESPONSES,
    tags=["documents"],
    summary="Get a document and its import status",
)
def get_document(
    id: int,
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> ApiResponse[DocumentItem]:
    document = service.repository.get_document(id)
    if document is None:
        raise AppError(ErrorCode.DOCUMENT_NOT_FOUND, "文档不存在", http_status=404)
    return ApiResponse(
        code=0,
        message="success",
        data=DocumentItem.model_validate(_schema_fields(DocumentItem, document)),
    )


@router.post(
    "/documents/{id}/reimport",
    response_model=ApiResponse[DocumentReimportAccepted],
    status_code=202,
    responses=CONTRACT_RESPONSES,
    tags=["documents"],
    summary="Reimport a failed document",
)
def reimport_document(
    id: int,
    background_tasks: BackgroundTasks,
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> ApiResponse[DocumentReimportAccepted]:
    document = service.reimport(id)
    background_tasks.add_task(service.import_document, id)
    return ApiResponse(
        code=0,
        message="accepted",
        data=DocumentReimportAccepted(document_id=id, status=document["status"]),
    )


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
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> ApiResponse[PageResult[ChunkItem]]:
    if service.repository.get_document(id) is None:
        raise AppError(ErrorCode.DOCUMENT_NOT_FOUND, "文档不存在", http_status=404)
    items, total = service.repository.list_chunks(id, page=query.page, size=query.size)
    return ApiResponse(
        code=0,
        message="success",
        data=PageResult(
            items=[
                ChunkItem.model_validate(_schema_fields(ChunkItem, item))
                for item in items
            ],
            page=query.page,
            size=query.size,
            total=total,
            pages=(total + query.size - 1) // query.size,
        ),
    )


def _schema_fields(model: type, source: dict) -> dict:
    return {field: source[field] for field in model.model_fields if field in source}


@router.post(
    "/sessions",
    response_model=ApiResponse[SessionItem],
    status_code=201,
    responses=IMPLEMENTED_RESPONSES,
    tags=["sessions"],
    summary="Create a chat session",
)
def create_session(
    payload: CreateSessionRequest,
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ApiResponse[SessionItem]:
    session = service.create_session(payload.title)
    return ApiResponse(
        code=0,
        message="success",
        data=SessionItem.model_validate(session),
    )


@router.get(
    "/sessions/{id}/messages",
    response_model=ApiResponse[list[MessageItem]],
    responses=IMPLEMENTED_RESPONSES,
    tags=["sessions"],
    summary="List messages for a session",
)
def list_session_messages(
    id: UUID,
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ApiResponse[list[MessageItem]]:
    if service.get_session(id) is None:
        raise AppError(ErrorCode.SESSION_NOT_FOUND, "会话不存在", http_status=404)
    messages = service.list_messages(id)
    return ApiResponse(
        code=0,
        message="success",
        data=[MessageItem.model_validate(message) for message in messages],
    )


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
        **IMPLEMENTED_RESPONSES,
    },
    tags=["chat"],
    summary="Stream a RAG answer using Server-Sent Events",
)
async def stream_chat(
    payload: ChatRequest,
    request: Request,
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> StreamingResponse:
    if service.get_session(payload.session_id) is None:
        raise AppError(ErrorCode.SESSION_NOT_FOUND, "会话不存在", http_status=404)
    return StreamingResponse(
        service.stream_chat(payload, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/tools/material-checklist",
    response_model=ApiResponse[ToolExecutionItem],
    responses=IMPLEMENTED_RESPONSES,
    tags=["tools"],
    summary="Generate a material checklist",
)
def material_checklist(
    payload: MaterialChecklistInput,
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ApiResponse[ToolExecutionItem]:
    return ApiResponse(
        code=0,
        message="success",
        data=service.execute_material_checklist(payload),
    )


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
def create_evaluation_run(
    payload: EvaluationRunCreate,
) -> ApiResponse[EvaluationRunJob]:
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
    responses=IMPLEMENTED_RESPONSES,
    tags=["missing-knowledge"],
    summary="List missing-knowledge topics",
)
def list_missing_knowledge(
    query: Annotated[MissingKnowledgeQuery, Query()],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ApiResponse[PageResult[MissingKnowledgeItem]]:
    items, total = service.list_missing_knowledge(query)
    return ApiResponse(
        code=0,
        message="success",
        data=PageResult(
            items=[
                MissingKnowledgeItem.model_validate(
                    _schema_fields(MissingKnowledgeItem, item)
                )
                for item in items
            ],
            page=query.page,
            size=query.size,
            total=total,
            pages=(total + query.size - 1) // query.size,
        ),
    )


@router.patch(
    "/missing-knowledge/{id}",
    response_model=ApiResponse[MissingKnowledgeItem],
    responses=IMPLEMENTED_RESPONSES,
    tags=["missing-knowledge"],
    summary="Update a missing-knowledge topic",
)
def update_missing_knowledge(
    id: int,
    payload: MissingKnowledgeUpdate,
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ApiResponse[MissingKnowledgeItem]:
    item = service.update_missing_knowledge(id, payload)
    return ApiResponse(
        code=0,
        message="success",
        data=MissingKnowledgeItem.model_validate(
            _schema_fields(MissingKnowledgeItem, item)
        ),
    )


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
