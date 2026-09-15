from datetime import UTC, datetime
from typing import Annotated, Generic, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, PlainSerializer

T = TypeVar("T")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


UtcDateTime = Annotated[
    datetime,
    AfterValidator(_as_utc),
    PlainSerializer(_format_utc, return_type=str, when_used="json"),
]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApiResponse(ApiModel, Generic[T]):
    code: int
    message: str
    data: T | None


class PageResult(ApiModel, Generic[T]):
    items: list[T]
    page: int = Field(ge=1)
    size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
    pages: int = Field(ge=0)


class HealthData(ApiModel):
    service: str
    database: str
    vector_store: str
    doc_converter: str
    llm_configured: bool
    embedding_provider: str
    embedding_model: str
    embedding_ready: bool
    embedding_index_compatible: bool


class PageQuery(ApiModel):
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)
