import sqlite3
import tempfile
from pathlib import Path

from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.schemas.contracts import (
    MissingKnowledgeQuery,
    MissingKnowledgeStatus,
    MissingKnowledgeUpdate,
)
from app.services.missing_knowledge import (
    MissingKnowledgeReason,
    MissingKnowledgeService,
)


def _service(path: Path) -> MissingKnowledgeService:
    schema = Path(__file__).parents[1] / "app" / "core" / "schema.sql"
    with sqlite3.connect(path) as connection:
        connection.executescript(schema.read_text(encoding="utf-8"))
    return MissingKnowledgeService(database_path=path)


def test_repeated_refusals_are_normalized_and_aggregated() -> None:
    with tempfile.TemporaryDirectory() as directory:
        service = _service(Path(directory) / "missing.db")

        first = service.record_refusal(
            "  公司拖欠工资怎么办？  ", MissingKnowledgeReason.NO_RETRIEVAL_RESULT
        )
        repeated = service.record_refusal(
            "公司拖欠工资怎么办！", MissingKnowledgeReason.LOW_RELEVANCE
        )

        assert first["topic_key"] == "wage_payment"
        assert first["sample_question"] == "公司拖欠工资怎么办"
        assert repeated["count"] == 2
        assert repeated["first_seen_at"] == first["first_seen_at"]
        assert repeated["sample_question"] == first["sample_question"]
        assert repeated["status"] == "PENDING"


def test_unknown_topics_use_other_bucket_and_management_filters_work() -> None:
    with tempfile.TemporaryDirectory() as directory:
        service = _service(Path(directory) / "missing.db")
        service.record_refusal(
            "关于某项特殊劳动权益如何处理？",
            MissingKnowledgeReason.INSUFFICIENT_EVIDENCE,
        )
        service.record_refusal(
            "社保转移需要什么手续？", MissingKnowledgeReason.NO_RETRIEVAL_RESULT
        )

        service.update(
            1,
            MissingKnowledgeUpdate(
                status=MissingKnowledgeStatus.RESOLVED, note="补充了资料"
            ),
        )
        items, total = service.list(
            MissingKnowledgeQuery(
                status=MissingKnowledgeStatus.RESOLVED, keyword="特殊"
            )
        )

        assert total == 1
        assert items[0]["topic_key"] == "other"
        assert items[0]["status"] == "RESOLVED"
        assert items[0]["note"] == "补充了资料"


def test_list_paginates_and_sorts_by_count() -> None:
    with tempfile.TemporaryDirectory() as directory:
        service = _service(Path(directory) / "missing.db")
        for _ in range(3):
            service.record_refusal(
                "单位不发工资怎么办？", MissingKnowledgeReason.NO_RETRIEVAL_RESULT
            )
        service.record_refusal(
            "劳动合同没签怎么办？", MissingKnowledgeReason.NO_RETRIEVAL_RESULT
        )

        items, total = service.list(MissingKnowledgeQuery(page=1, size=1))

        assert total == 2
        assert len(items) == 1
        assert items[0]["topic_key"] == "wage_payment"
        assert items[0]["count"] == 3


def test_update_unknown_item_uses_missing_knowledge_error_code() -> None:
    with tempfile.TemporaryDirectory() as directory:
        service = _service(Path(directory) / "missing.db")

        try:
            service.update(
                999,
                MissingKnowledgeUpdate(
                    status=MissingKnowledgeStatus.IGNORED, note=None
                ),
            )
        except AppError as error:
            assert error.code == ErrorCode.MISSING_KNOWLEDGE_NOT_FOUND
            assert error.http_status == 404
        else:
            raise AssertionError("Expected a missing knowledge not found error")
