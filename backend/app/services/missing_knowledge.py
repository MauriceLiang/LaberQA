"""Classification and management of production evidence-gate refusals."""

from __future__ import annotations

import logging
import re
import unicodedata
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.repositories.missing_knowledge_repository import MissingKnowledgeRepository
from app.schemas.contracts import (
    MissingKnowledgeQuery,
    MissingKnowledgeUpdate,
)

logger = logging.getLogger(__name__)


class MissingKnowledgeReason(StrEnum):
    NO_RETRIEVAL_RESULT = "NO_RETRIEVAL_RESULT"
    LOW_RELEVANCE = "LOW_RELEVANCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ExecutionMode(StrEnum):
    PRODUCTION = "PRODUCTION"
    EVALUATION = "EVALUATION"
    EXPERIMENT = "EXPERIMENT"


_TOPICS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("wage_payment", "工资支付与欠薪", ("工资", "欠薪", "薪资", "加班费")),
    (
        "termination",
        "劳动关系解除与经济补偿",
        ("解除", "辞退", "开除", "裁员", "经济补偿", "赔偿金"),
    ),
    ("labor_contract", "劳动合同与劳动关系", ("劳动合同", "劳动关系", "未签合同")),
    ("social_insurance", "社会保险与住房公积金", ("社保", "社会保险", "公积金")),
    (
        "working_time",
        "工作时间与休息休假",
        ("加班", "工时", "工作时间", "休息", "年假", "休假"),
    ),
    ("work_injury", "工伤认定与待遇", ("工伤", "职业病")),
)


class MissingKnowledgeService:
    def __init__(
        self,
        *,
        repository: MissingKnowledgeRepository | None = None,
        database_path: Path | None = None,
    ) -> None:
        self.repository = repository or MissingKnowledgeRepository(database_path)

    def record_refusal(
        self, question: str, reason: MissingKnowledgeReason
    ) -> dict[str, Any]:
        if not isinstance(reason, MissingKnowledgeReason):
            raise TypeError(f"Unsupported missing-knowledge reason: {reason}")
        normalized = _normalize_question(question)
        topic = _classify(normalized)
        if topic is None:
            logger.error(
                "Could not classify a production refusal; using the other topic bucket"
            )
            topic_key, missing_area = "other", "其他劳动权益问题"
        else:
            topic_key, missing_area = topic
        return self.repository.record(topic_key, normalized, missing_area)

    def list(self, query: MissingKnowledgeQuery) -> tuple[list[dict[str, Any]], int]:
        return self.repository.list(
            page=query.page,
            size=query.size,
            status=query.status.value if query.status else None,
            keyword=query.keyword,
            sort=query.sort,
        )

    def update(self, item_id: int, payload: MissingKnowledgeUpdate) -> dict[str, Any]:
        item = self.repository.update(item_id, payload.status.value, payload.note)
        if item is None:
            raise AppError(
                ErrorCode.MISSING_KNOWLEDGE_NOT_FOUND,
                "缺失知识记录不存在",
                http_status=404,
            )
        return item


def _normalize_question(question: str) -> str:
    normalized = unicodedata.normalize("NFKC", question)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized.rstrip(" ?？。.!！,，;；:：")


def _classify(question: str) -> tuple[str, str] | None:
    for key, area, keywords in _TOPICS:
        if any(keyword in question for keyword in keywords):
            return key, area
    return None
