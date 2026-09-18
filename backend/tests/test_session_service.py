import sqlite3
from pathlib import Path
from uuid import UUID

import pytest

from app.core.errors import AppError
from app.repositories.session_repository import SessionRepository
from app.schemas.contracts import MessageItem, SessionItem
from app.services.session_service import SessionService

SCHEMA_PATH = Path(__file__).parents[1] / "app" / "core" / "schema.sql"


@pytest.fixture
def service(tmp_path: Path) -> SessionService:
    database_path = tmp_path / "sessions.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return SessionService(repository=SessionRepository(database_path))


def test_create_session_and_validate_message_history_contract(
    service: SessionService,
) -> None:
    session = service.create_session("劳动咨询")

    validated = SessionItem.model_validate(session)
    assert validated.title == "劳动咨询"
    assert str(validated.id) == session["id"]
    assert session == service.get_session(validated.id)
    assert service.list_messages(validated.id) == []

    user_message = service.create_user_message(validated.id, "试用期被辞退有补偿吗？")
    assert user_message["role"] == "user"
    assert user_message["rewritten_question"] == "试用期被辞退有补偿吗？"
    assert user_message["answer_style"] is None
    assert user_message["refused"] is None
    assert user_message["citations"] == []
    assert user_message["tool_executions"] == []
    MessageItem.model_validate(user_message)

    service.set_rewritten_question(user_message["id"], "试用期解除劳动合同的补偿")
    assert service.list_messages(validated.id)[0]["rewritten_question"] == (
        "试用期解除劳动合同的补偿"
    )


def test_list_sessions_returns_recent_sessions_with_messages_only(
    service: SessionService,
) -> None:
    empty = service.create_session("空会话")
    first = service.create_session("第一段咨询")
    second = service.create_session("第二段咨询")
    service.create_user_message(first["id"], "第一个问题")
    service.create_user_message(second["id"], "第二个问题")

    recent = service.list_sessions()

    assert {session["id"] for session in recent} == {first["id"], second["id"]}
    assert empty["id"] not in {session["id"] for session in recent}


def test_history_is_session_scoped_and_aggregates_sources_and_tools(
    service: SessionService,
) -> None:
    session = service.create_session()
    other_session = service.create_session()
    user_message = service.create_user_message(session["id"], "工资拖欠怎么处理？")
    service.create_user_message(other_session["id"], "另一会话内容")

    database_path = service.repository.database_path
    with sqlite3.connect(database_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO document (file_name, file_type, file_path, status)
            VALUES ('劳动合同法.pdf', 'pdf', '/tmp/law.pdf', 'SUCCESS')
            """
        )
        document_id = cursor.lastrowid
        cursor = connection.execute(
            """
            INSERT INTO chunk (document_id, chunk_no, content, vector_key)
            VALUES (?, 1, '工资支付条款', 'chunk:test')
            """,
            (document_id,),
        )
        chunk_id = cursor.lastrowid

    assistant = service.persist_assistant(
        session["id"],
        "可以先保存工资记录并咨询当地劳动保障部门。",
        "plain",
        False,
        [
            {
                "chunk_id": chunk_id,
                "document_id": document_id,
                "file_name": "劳动合同法.pdf",
                "chunk_no": 1,
                "content": "工资支付条款",
                "score": 0.91,
                "retrieval_score": 0.82,
                "rerank_score": None,
                "rank_no": 1,
            }
        ],
        [
            {
                "tool_name": "generate_rights_material_checklist",
                "input": {
                    "dispute_type": "拖欠工资",
                    "description": "公司未按时支付工资",
                },
                "output": {
                    "materials": ["劳动合同", "工资流水"],
                    "note": "整理材料后咨询当地劳动保障部门。",
                },
            }
        ],
    )

    history = service.list_messages(session["id"])
    assert [message["id"] for message in history] == [
        user_message["id"],
        assistant["id"],
    ]
    assert history[-1]["citations"] == [
        {
            "chunk_id": chunk_id,
            "document_id": document_id,
            "file_name": "劳动合同法.pdf",
            "chunk_no": 1,
            "content": "工资支付条款",
            "score": 0.91,
            "retrieval_score": 0.82,
            "rerank_score": None,
            "rank_no": 1,
        }
    ]
    assert history[-1]["tool_executions"][0]["input"]["dispute_type"] == "拖欠工资"
    assert len(service.list_messages(other_session["id"])) == 1
    assert all(message["session_id"] == session["id"] for message in history)
    for message in history:
        MessageItem.model_validate(message)


def test_recent_context_returns_last_complete_pairs_in_time_order(
    service: SessionService,
) -> None:
    session = service.create_session()
    for turn in range(5):
        service.create_user_message(session["id"], f"问题 {turn}")
        service.persist_assistant(session["id"], f"回答 {turn}", "plain", False, [])
    service.create_user_message(session["id"], "尚未回答的问题")

    context = service.get_recent_context(session["id"], turns=3)

    assert [(message["role"], message["content"]) for message in context] == [
        ("user", "问题 2"),
        ("assistant", "回答 2"),
        ("user", "问题 3"),
        ("assistant", "回答 3"),
        ("user", "问题 4"),
        ("assistant", "回答 4"),
    ]
    assert service.get_recent_context(session["id"], turns=0) == []
    with pytest.raises(ValueError, match="turns"):
        service.get_recent_context(session["id"], turns=-1)


def test_assistant_citations_and_tools_are_persisted_atomically(
    service: SessionService,
) -> None:
    session = service.create_session()
    service.create_user_message(session["id"], "问题")
    tool_execution = {
        "tool_name": "generate_rights_material_checklist",
        "input": {"dispute_type": "工资", "description": "拖欠工资"},
        "output": {"materials": ["工资流水"], "note": "保存相关凭证。"},
    }

    with pytest.raises(sqlite3.IntegrityError):
        service.persist_assistant(
            session["id"],
            "回答",
            "plain",
            False,
            [
                {
                    "chunk_id": 999999,
                    "document_id": 1,
                    "file_name": "不存在.pdf",
                    "chunk_no": 1,
                    "content": "不存在",
                    "score": 0.8,
                    "retrieval_score": 0.8,
                    "rerank_score": None,
                    "rank_no": 1,
                }
            ],
            [tool_execution],
        )

    history = service.list_messages(session["id"])
    assert [message["role"] for message in history] == ["user"]
    with sqlite3.connect(service.repository.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM citation").fetchone()[0] == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM tool_execution").fetchone()[0] == 0
        )


def test_unknown_session_is_rejected_for_history_and_user_writes(
    service: SessionService,
) -> None:
    missing_session_id = str(UUID("00000000-0000-0000-0000-000000000001"))

    with pytest.raises(AppError) as error:
        service.list_messages(missing_session_id)
    assert error.value.code == 40402

    with pytest.raises(AppError) as error:
        service.create_user_message(missing_session_id, "问题")
    assert error.value.code == 40402
