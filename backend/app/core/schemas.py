from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int
    message: str
    data: T | None


class HealthData(BaseModel):
    service: str
    database: str
    vector_store: str
    doc_converter: str
    llm_configured: bool
    embedding_provider: str
    embedding_model: str
    embedding_ready: bool
    embedding_index_compatible: bool
