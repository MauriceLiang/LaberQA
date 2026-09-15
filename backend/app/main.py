import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.api.contracts import router as contracts_router
from app.api.health import router as health_router
from app.core.config import settings
from app.core.database import initialize_database
from app.core.errors import register_exception_handlers
from app.core.logging_config import configure_logging
from app.services.chat_service import ChatService
from app.services.document_service import DocumentService
from app.services.retrieval import RetrievalService
from app.services.session_service import SessionService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    initialize_database()
    document_service = DocumentService(settings)
    document_service.recover_interrupted_imports()
    app.state.document_service = document_service
    session_service = SessionService(database_path=settings.database_path)
    app.state.session_service = session_service
    app.state.chat_service = ChatService(
        session_service,
        RetrievalService(
            settings,
            repository=document_service.repository,
            embedding_service=document_service.embedding_service,
            vector_store=document_service.vector_store,
        ),
        settings,
    )
    logger.info("Application startup complete")
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
app.include_router(health_router, prefix=settings.api_prefix)
app.include_router(contracts_router, prefix=settings.api_prefix)
register_exception_handlers(app)


@app.middleware("http")
async def add_request_id(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    request_id = uuid4().hex
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response
