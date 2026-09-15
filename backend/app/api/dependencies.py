from fastapi import Request

from app.services.chat_service import ChatService
from app.services.document_service import DocumentService
from app.services.evaluation_service import EvaluationService


def get_document_service(request: Request) -> DocumentService:
    return request.app.state.document_service


def get_chat_service(request: Request) -> ChatService:
    return request.app.state.chat_service


def get_evaluation_service(request: Request) -> EvaluationService:
    return request.app.state.evaluation_service
