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

from app.api.dependencies import (
    get_chat_service,
    get_document_service,
    get_evaluation_service,
    get_retrieval_experiment_service,
)
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
    EvaluationCaseCreate,
    EvaluationCaseQuery,
    EvaluationCaseUpdate,
    EvaluationRunCreate,
    EvaluationRunDetail,
    EvaluationRunJob,
    EvaluationRunQuery,
    EvaluationRunSummary,
    ExperimentCopy,
    ExperimentCreate,
    ExperimentDetail,
    ExperimentJob,
    ExperimentQuery,
    ExperimentSummary,
    JobStatus,
    MaterialChecklistInput,
    MessageItem,
    MissingKnowledgeItem,
    MissingKnowledgeQuery,
    MissingKnowledgeUpdate,
    RetrievalPreviewRequest,
    RetrievalPreviewResponse,
    RetrievalStrategy,
    RetrievalStrategyCreate,
    RetrievalStrategyStatusUpdate,
    RetrievalStrategyUpdate,
    RetrievalStrategyVersion,
    SessionItem,
    ToolExecutionItem,
)
from app.services.chat_service import ChatService
from app.services.document_service import DocumentService
from app.services.evaluation_service import EvaluationService
from app.services.retrieval_experiment_service import RetrievalExperimentService

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


@router.delete(
    "/documents/{id}",
    response_model=ApiResponse[None],
    responses=CONTRACT_RESPONSES,
    tags=["documents"],
    summary="Delete a document and its derived data",
)
def delete_document(
    id: int,
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> ApiResponse[None]:
    service.delete_document(id)
    return ApiResponse(code=0, message="deleted", data=None)


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
    "/sessions",
    response_model=ApiResponse[list[SessionItem]],
    responses=IMPLEMENTED_RESPONSES,
    tags=["sessions"],
    summary="List recent chat sessions",
)
def list_sessions(
    service: Annotated[ChatService, Depends(get_chat_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ApiResponse[list[SessionItem]]:
    sessions = service.list_sessions(limit)
    return ApiResponse(
        code=0,
        message="success",
        data=[SessionItem.model_validate(session) for session in sessions],
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
    responses=IMPLEMENTED_RESPONSES,
    tags=["evaluations"],
    summary="List evaluation cases",
)
def list_evaluation_cases(
    query: Annotated[EvaluationCaseQuery, Query()],
    service: Annotated[EvaluationService, Depends(get_evaluation_service)],
) -> ApiResponse[PageResult[EvaluationCase]]:
    items, total = service.list_cases(
        page=query.page,
        size=query.size,
        topic=query.topic,
        expected_type=query.expected_type.value if query.expected_type else None,
        is_multi_turn=query.is_multi_turn,
        origin=query.origin.value if query.origin else None,
        status=query.status.value if query.status else None,
        include_archived=query.include_archived,
    )
    return ApiResponse(
        code=0,
        message="success",
        data=PageResult(
            items=[EvaluationCase.model_validate(item) for item in items],
            page=query.page,
            size=query.size,
            total=total,
            pages=(total + query.size - 1) // query.size,
        ),
    )


@router.post(
    "/evaluations/cases",
    response_model=ApiResponse[EvaluationCase],
    status_code=201,
    responses=IMPLEMENTED_RESPONSES,
    tags=["evaluations"],
    summary="Create a custom evaluation case",
)
def create_evaluation_case(
    payload: EvaluationCaseCreate,
    service: Annotated[EvaluationService, Depends(get_evaluation_service)],
) -> ApiResponse[EvaluationCase]:
    return ApiResponse(
        code=0,
        message="created",
        data=EvaluationCase.model_validate(service.create_case(payload)),
    )


@router.get(
    "/evaluations/cases/{id}",
    response_model=ApiResponse[EvaluationCase],
    responses=IMPLEMENTED_RESPONSES,
    tags=["evaluations"],
    summary="Get an evaluation case",
)
def get_evaluation_case(
    id: int,
    service: Annotated[EvaluationService, Depends(get_evaluation_service)],
) -> ApiResponse[EvaluationCase]:
    return ApiResponse(
        code=0,
        message="success",
        data=EvaluationCase.model_validate(
            service.get_case(id, include_archived=True)
        ),
    )


@router.patch(
    "/evaluations/cases/{id}",
    response_model=ApiResponse[EvaluationCase],
    responses=IMPLEMENTED_RESPONSES,
    tags=["evaluations"],
    summary="Update a custom evaluation case",
)
def update_evaluation_case(
    id: int,
    payload: EvaluationCaseUpdate,
    service: Annotated[EvaluationService, Depends(get_evaluation_service)],
) -> ApiResponse[EvaluationCase]:
    return ApiResponse(
        code=0,
        message="updated",
        data=EvaluationCase.model_validate(service.update_case(id, payload)),
    )


@router.delete(
    "/evaluations/cases/{id}",
    response_model=ApiResponse[None],
    responses=IMPLEMENTED_RESPONSES,
    tags=["evaluations"],
    summary="Archive a custom evaluation case",
)
def delete_evaluation_case(
    id: int,
    service: Annotated[EvaluationService, Depends(get_evaluation_service)],
) -> ApiResponse[None]:
    service.archive_case(id)
    return ApiResponse(code=0, message="deleted", data=None)


@router.post(
    "/evaluations/runs",
    response_model=ApiResponse[EvaluationRunJob],
    status_code=202,
    responses=IMPLEMENTED_RESPONSES,
    tags=["evaluations"],
    summary="Create an evaluation run",
)
def create_evaluation_run(
    payload: EvaluationRunCreate,
    background_tasks: BackgroundTasks,
    service: Annotated[EvaluationService, Depends(get_evaluation_service)],
) -> ApiResponse[EvaluationRunJob]:
    run = service.create_run(payload)
    background_tasks.add_task(service.execute_run, int(run["id"]))
    return ApiResponse(
        code=0,
        message="accepted",
        data=EvaluationRunJob(
            run_id=int(run["id"]),
            status=JobStatus.PENDING,
            progress_current=0,
            progress_total=int(run["progress_total"]),
            error_message=None,
        ),
    )


@router.get(
    "/evaluations/runs",
    response_model=ApiResponse[PageResult[EvaluationRunSummary]],
    responses=IMPLEMENTED_RESPONSES,
    tags=["evaluations"],
    summary="List evaluation runs",
)
def list_evaluation_runs(
    query: Annotated[EvaluationRunQuery, Query()],
    service: Annotated[EvaluationService, Depends(get_evaluation_service)],
) -> ApiResponse[PageResult[EvaluationRunSummary]]:
    items, total = service.list_runs(
        page=query.page,
        size=query.size,
        status=query.status.value if query.status else None,
    )
    return ApiResponse(
        code=0,
        message="success",
        data=PageResult(
            items=[EvaluationRunSummary.model_validate(item) for item in items],
            page=query.page,
            size=query.size,
            total=total,
            pages=(total + query.size - 1) // query.size,
        ),
    )


@router.get(
    "/evaluations/runs/{id}",
    response_model=ApiResponse[EvaluationRunDetail],
    responses=IMPLEMENTED_RESPONSES,
    tags=["evaluations"],
    summary="Get an evaluation run",
)
def get_evaluation_run(
    id: int,
    service: Annotated[EvaluationService, Depends(get_evaluation_service)],
) -> ApiResponse[EvaluationRunDetail]:
    return ApiResponse(
        code=0,
        message="success",
        data=EvaluationRunDetail.model_validate(
            _schema_fields(EvaluationRunDetail, service.get_run(id))
        ),
    )


@router.delete(
    "/evaluations/runs/{id}",
    response_model=ApiResponse[None],
    responses=IMPLEMENTED_RESPONSES,
    tags=["evaluations"],
    summary="Delete a completed or failed evaluation run",
)
def delete_evaluation_run(
    id: int,
    service: Annotated[EvaluationService, Depends(get_evaluation_service)],
) -> ApiResponse[None]:
    service.delete_run(id)
    return ApiResponse(code=0, message="deleted", data=None)


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
    "/retrieval-strategies",
    response_model=ApiResponse[list[RetrievalStrategy]],
    responses=IMPLEMENTED_RESPONSES,
    tags=["retrieval-experiments"],
    summary="List retrieval strategies",
)
def list_retrieval_strategies(
    service: Annotated[
        RetrievalExperimentService, Depends(get_retrieval_experiment_service)
    ],
    include_archived: bool = Query(default=False),
) -> ApiResponse[list[RetrievalStrategy]]:
    return ApiResponse(
        code=0,
        message="success",
        data=[
            RetrievalStrategy.model_validate(item)
                for item in service.list_strategies(include_archived=include_archived)
        ],
    )


@router.post(
    "/retrieval-strategies",
    response_model=ApiResponse[RetrievalStrategy],
    status_code=201,
    responses=IMPLEMENTED_RESPONSES,
    tags=["retrieval-experiments"],
    summary="Create a retrieval strategy",
)
def create_retrieval_strategy(
    payload: RetrievalStrategyCreate,
    service: Annotated[
        RetrievalExperimentService, Depends(get_retrieval_experiment_service)
    ],
) -> ApiResponse[RetrievalStrategy]:
    return ApiResponse(
        code=0,
        message="created",
        data=RetrievalStrategy.model_validate(service.create_strategy(payload)),
    )


@router.patch(
    "/retrieval-strategies/{id}/status",
    response_model=ApiResponse[RetrievalStrategy],
    responses=IMPLEMENTED_RESPONSES,
    tags=["retrieval-experiments"],
    summary="Enable or disable a custom retrieval strategy",
)
def update_retrieval_strategy_status(
    id: int,
    payload: RetrievalStrategyStatusUpdate,
    service: Annotated[
        RetrievalExperimentService, Depends(get_retrieval_experiment_service)
    ],
) -> ApiResponse[RetrievalStrategy]:
    return ApiResponse(
        code=0,
        message="success",
        data=RetrievalStrategy.model_validate(
            service.set_strategy_active(id, payload.is_active)
        ),
    )


@router.get(
    "/retrieval-strategies/{id}/versions",
    response_model=ApiResponse[list[RetrievalStrategyVersion]],
    responses=IMPLEMENTED_RESPONSES,
    tags=["retrieval-experiments"],
    summary="List retrieval strategy versions",
)
def list_retrieval_strategy_versions(
    id: int,
    service: Annotated[
        RetrievalExperimentService, Depends(get_retrieval_experiment_service)
    ],
) -> ApiResponse[list[RetrievalStrategyVersion]]:
    return ApiResponse(
        code=0,
        message="success",
        data=[
            RetrievalStrategyVersion.model_validate(item)
            for item in service.list_strategy_versions(id)
        ],
    )


@router.post(
    "/retrieval-strategies/{id}/versions/{version}/restore",
    response_model=ApiResponse[RetrievalStrategy],
    responses=IMPLEMENTED_RESPONSES,
    tags=["retrieval-experiments"],
    summary="Restore a retrieval strategy version",
)
def restore_retrieval_strategy_version(
    id: int,
    version: int,
    service: Annotated[
        RetrievalExperimentService, Depends(get_retrieval_experiment_service)
    ],
) -> ApiResponse[RetrievalStrategy]:
    return ApiResponse(
        code=0,
        message="restored",
        data=RetrievalStrategy.model_validate(
            service.restore_strategy_version(id, version)
        ),
    )


@router.post(
    "/retrieval-strategies/{id}/archive",
    response_model=ApiResponse[RetrievalStrategy],
    responses=IMPLEMENTED_RESPONSES,
    tags=["retrieval-experiments"],
    summary="Archive a custom retrieval strategy",
)
def archive_retrieval_strategy(
    id: int,
    service: Annotated[
        RetrievalExperimentService, Depends(get_retrieval_experiment_service)
    ],
) -> ApiResponse[RetrievalStrategy]:
    return ApiResponse(
        code=0,
        message="archived",
        data=RetrievalStrategy.model_validate(service.archive_strategy(id)),
    )


@router.post(
    "/retrieval-strategies/{id}/restore",
    response_model=ApiResponse[RetrievalStrategy],
    responses=IMPLEMENTED_RESPONSES,
    tags=["retrieval-experiments"],
    summary="Restore an archived custom retrieval strategy",
)
def restore_retrieval_strategy(
    id: int,
    service: Annotated[
        RetrievalExperimentService, Depends(get_retrieval_experiment_service)
    ],
) -> ApiResponse[RetrievalStrategy]:
    return ApiResponse(
        code=0,
        message="restored",
        data=RetrievalStrategy.model_validate(service.restore_strategy(id)),
    )


@router.patch(
    "/retrieval-strategies/{id}",
    response_model=ApiResponse[RetrievalStrategy],
    responses=IMPLEMENTED_RESPONSES,
    tags=["retrieval-experiments"],
    summary="Update a custom retrieval strategy",
)
def update_retrieval_strategy(
    id: int,
    payload: RetrievalStrategyUpdate,
    service: Annotated[
        RetrievalExperimentService, Depends(get_retrieval_experiment_service)
    ],
) -> ApiResponse[RetrievalStrategy]:
    return ApiResponse(
        code=0,
        message="success",
        data=RetrievalStrategy.model_validate(service.update_strategy(id, payload)),
    )


@router.delete(
    "/retrieval-strategies/{id}",
    response_model=ApiResponse[None],
    responses=IMPLEMENTED_RESPONSES,
    tags=["retrieval-experiments"],
    summary="Delete a custom retrieval strategy",
)
def delete_retrieval_strategy(
    id: int,
    service: Annotated[
        RetrievalExperimentService, Depends(get_retrieval_experiment_service)
    ],
) -> ApiResponse[None]:
    service.delete_strategy(id)
    return ApiResponse(code=0, message="deleted", data=None)


@router.get(
    "/retrieval-experiments",
    response_model=ApiResponse[PageResult[ExperimentSummary]],
    responses=IMPLEMENTED_RESPONSES,
    tags=["retrieval-experiments"],
    summary="List retrieval experiments",
)
def list_experiments(
    query: Annotated[ExperimentQuery, Query()],
    service: Annotated[
        RetrievalExperimentService, Depends(get_retrieval_experiment_service)
    ],
) -> ApiResponse[PageResult[ExperimentSummary]]:
    items, total = service.list_experiments(
        page=query.page,
        size=query.size,
        status=query.status.value if query.status else None,
        include_archived=query.include_archived,
    )
    return ApiResponse(
        code=0,
        message="success",
        data=PageResult(
            items=[ExperimentSummary.model_validate(item) for item in items],
            page=query.page,
            size=query.size,
            total=total,
            pages=(total + query.size - 1) // query.size,
        ),
    )


@router.post(
    "/retrieval-experiments",
    response_model=ApiResponse[ExperimentJob],
    status_code=202,
    responses=IMPLEMENTED_RESPONSES,
    tags=["retrieval-experiments"],
    summary="Create a retrieval experiment",
)
def create_experiment(
    payload: ExperimentCreate,
    background_tasks: BackgroundTasks,
    service: Annotated[
        RetrievalExperimentService, Depends(get_retrieval_experiment_service)
    ],
) -> ApiResponse[ExperimentJob]:
    experiment = service.create_experiment(payload)
    background_tasks.add_task(service.execute_experiment, int(experiment["id"]))
    return ApiResponse(
        code=0,
        message="accepted",
        data=ExperimentJob(
            experiment_id=int(experiment["id"]),
            status=JobStatus.PENDING,
            progress_current=0,
            progress_total=int(experiment["progress_total"]),
            error_message=None,
        ),
    )


@router.post(
    "/retrieval-experiments/preview",
    response_model=ApiResponse[RetrievalPreviewResponse],
    responses=IMPLEMENTED_RESPONSES,
    tags=["retrieval-experiments"],
    summary="Preview one retrieval experiment query",
)
async def preview_retrieval_experiment(
    payload: RetrievalPreviewRequest,
    service: Annotated[
        RetrievalExperimentService, Depends(get_retrieval_experiment_service)
    ],
) -> ApiResponse[RetrievalPreviewResponse]:
    result = await service.preview(payload)
    return ApiResponse(
        code=0,
        message="success",
        data=RetrievalPreviewResponse.model_validate(result),
    )


@router.post(
    "/retrieval-experiments/{id}/copy",
    response_model=ApiResponse[ExperimentJob],
    status_code=202,
    responses=IMPLEMENTED_RESPONSES,
    tags=["retrieval-experiments"],
    summary="Copy a retrieval experiment",
)
def copy_experiment(
    id: int,
    payload: ExperimentCopy,
    background_tasks: BackgroundTasks,
    service: Annotated[
        RetrievalExperimentService, Depends(get_retrieval_experiment_service)
    ],
) -> ApiResponse[ExperimentJob]:
    experiment = service.copy_experiment(id, payload.name)
    background_tasks.add_task(service.execute_experiment, int(experiment["id"]))
    return ApiResponse(
        code=0,
        message="accepted",
        data=ExperimentJob(
            experiment_id=int(experiment["id"]),
            status=JobStatus.PENDING,
            progress_current=0,
            progress_total=int(experiment["progress_total"]),
            error_message=None,
        ),
    )


@router.get(
    "/retrieval-experiments/{id}/export",
    response_model=ApiResponse[str],
    responses=IMPLEMENTED_RESPONSES,
    tags=["retrieval-experiments"],
    summary="Export retrieval experiment results",
)
def export_experiment(
    id: int,
    service: Annotated[
        RetrievalExperimentService, Depends(get_retrieval_experiment_service)
    ],
) -> ApiResponse[str]:
    return ApiResponse(
        code=0,
        message="success",
        data=service.export_experiment(id),
    )


@router.post(
    "/retrieval-experiments/{id}/archive",
    response_model=ApiResponse[ExperimentSummary],
    responses=IMPLEMENTED_RESPONSES,
    tags=["retrieval-experiments"],
    summary="Archive a completed retrieval experiment",
)
def archive_experiment(
    id: int,
    service: Annotated[
        RetrievalExperimentService, Depends(get_retrieval_experiment_service)
    ],
) -> ApiResponse[ExperimentSummary]:
    return ApiResponse(
        code=0,
        message="archived",
        data=ExperimentSummary.model_validate(service.archive_experiment(id)),
    )


@router.post(
    "/retrieval-experiments/{id}/restore",
    response_model=ApiResponse[ExperimentSummary],
    responses=IMPLEMENTED_RESPONSES,
    tags=["retrieval-experiments"],
    summary="Restore an archived retrieval experiment",
)
def restore_experiment(
    id: int,
    service: Annotated[
        RetrievalExperimentService, Depends(get_retrieval_experiment_service)
    ],
) -> ApiResponse[ExperimentSummary]:
    return ApiResponse(
        code=0,
        message="restored",
        data=ExperimentSummary.model_validate(service.restore_experiment(id)),
    )


@router.get(
    "/retrieval-experiments/{id}",
    response_model=ApiResponse[ExperimentDetail],
    responses=IMPLEMENTED_RESPONSES,
    tags=["retrieval-experiments"],
    summary="Get a retrieval experiment",
)
def get_experiment(
    id: int,
    service: Annotated[
        RetrievalExperimentService, Depends(get_retrieval_experiment_service)
    ],
) -> ApiResponse[ExperimentDetail]:
    return ApiResponse(
        code=0,
        message="success",
        data=ExperimentDetail.model_validate(
            _schema_fields(ExperimentDetail, service.get_experiment(id))
        ),
    )


@router.delete(
    "/retrieval-experiments/{id}",
    response_model=ApiResponse[None],
    responses=IMPLEMENTED_RESPONSES,
    tags=["retrieval-experiments"],
    summary="Delete a completed retrieval experiment",
)
def delete_experiment(
    id: int,
    service: Annotated[
        RetrievalExperimentService, Depends(get_retrieval_experiment_service)
    ],
) -> ApiResponse[None]:
    service.delete_experiment(id)
    return ApiResponse(code=0, message="deleted", data=None)
