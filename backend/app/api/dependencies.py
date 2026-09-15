from fastapi import Request

from app.services.chat_service import ChatService
from app.services.document_service import DocumentService


def get_document_service(request: Request) -> DocumentService:
    return request.app.state.document_service


def get_chat_service(request: Request) -> ChatService:
    return request.app.state.chat_service
