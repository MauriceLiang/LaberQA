from fastapi import APIRouter, Request

from app.core.config import settings
from app.core.database import database_is_ready
from app.core.schemas import ApiResponse, HealthData
from app.services.document_parser import find_doc_converter
from app.services.embedding import local_embedding_is_cached
from app.services.vector_store import VectorStoreSignatureMismatch

router = APIRouter()


@router.get("/health", response_model=ApiResponse[HealthData])
def get_health(request: Request) -> ApiResponse[HealthData]:
    document_service = request.app.state.document_service
    vector_store = document_service.vector_store
    production_index = vector_store.index_path
    index_exists = production_index.is_file()
    converter_ready = find_doc_converter(settings.doc_converter) is not None
    embedding_ready = (
        local_embedding_is_cached()
        if settings.embedding_provider == "local"
        else bool(
            settings.embedding_api_key
            and settings.embedding_base_url
            and settings.embedding_api_model
        )
    )
    try:
        compatible = vector_store.is_signature_compatible()
    except VectorStoreSignatureMismatch:
        compatible = False
    store_status = vector_store.status

    return ApiResponse(
        code=0,
        message="success",
        data=HealthData(
            service="ok",
            database="ok" if database_is_ready() else "unavailable",
            vector_store=(
                "ready" if index_exists and store_status == "ready" else store_status
            ),
            doc_converter="ready" if converter_ready else "unavailable",
            llm_configured=bool(settings.llm_api_key),
            embedding_provider=settings.embedding_provider,
            embedding_model=settings.embedding_model,
            embedding_ready=embedding_ready,
            embedding_index_compatible=compatible if index_exists else True,
        ),
    )
