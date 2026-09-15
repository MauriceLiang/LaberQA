from fastapi import Request

from app.services.document_service import DocumentService


def get_document_service(request: Request) -> DocumentService:
    return request.app.state.document_service
