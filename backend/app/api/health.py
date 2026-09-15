from pathlib import Path
import shutil

from fastapi import APIRouter

from app.core.config import settings
from app.core.database import database_is_ready
from app.core.schemas import ApiResponse, HealthData
from app.services.embedding import local_embedding_is_cached

router = APIRouter()


@router.get("/health", response_model=ApiResponse[HealthData])
def get_health() -> ApiResponse[HealthData]:
    production_index = settings.faiss_path / "production" / "index.faiss"
    index_exists = production_index.is_file()
    converter_ready = bool(shutil.which("soffice") or shutil.which("libreoffice"))
    embedding_ready = (
        local_embedding_is_cached() if settings.embedding_provider == "local" else False
    )

    return ApiResponse(
        code=0,
        message="success",
        data=HealthData(
            service="ok",
            database="ok" if database_is_ready() else "unavailable",
            vector_store="ready" if index_exists else "not_initialized",
            doc_converter="ready" if converter_ready else "unavailable",
            llm_configured=bool(settings.llm_api_key),
            embedding_provider=settings.embedding_provider,
            embedding_model=settings.embedding_model,
            embedding_ready=embedding_ready,
            embedding_index_compatible=not index_exists,
        ),
    )
