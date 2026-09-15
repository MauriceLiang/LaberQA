import asyncio
import sqlite3
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID

from app.core.config import Settings
from app.schemas.contracts import ChatRequest
from app.services.chat_service import ChatService
from app.services.session_service import SessionService
from app.services.vector_store import VectorStoreNotInitialized


class FakeRequest:
    def __init__(self, disconnected: list[bool] | None = None) -> None:
        self.disconnected = iter(disconnected or [])

    async def is_disconnected(self) -> bool:
        return next(self.disconnected, False)


class FakeRetrieval:
    def __init__(self, evidence: list[dict[str, Any]] | None = None) -> None:
        self.evidence = evidence or []
        self.error: Exception | None = None
        self.queries: list[str] = []

    def retrieve(self, query: str) -> list[dict[str, Any]]:
        self.queries.append(query)
        if self.error:
            raise self.error
        return self.evidence


class FakeLlm:
    def __init__(self) -> None:
        self.completions: list[tuple[list[dict[str, str]], bool]] = []

    async def complete(
        self, messages: list[dict[str, str]], *, json_mode: bool = False
    ) -> str:
        self.completions.append((messages, json_mode))
        if json_mode:
            return '{"sufficient":true,"reason":"evidence supports the answer"}'
        return "那公司以不符合录用条件解除劳动关系是否合法？"

    async def stream(self, messages: list[dict[str, str]]):
        yield "应结合具体证据判断。"
        yield "建议保留书面材料。"


class EmptyStreamLlm(FakeLlm):
    async def stream(self, messages: list[dict[str, str]]):
        if False:
            yield ""


def _create_database(path: Path) -> None:
    schema = Path(__file__).parents[1] / "app" / "core" / "schema.sql"
    with sqlite3.connect(path) as connection:
        connection.executescript(schema.read_text(encoding="utf-8"))
        connection.execute(
            """
            INSERT INTO document (file_name, file_type, file_path, status, chunk_count)
            VALUES ('劳动合同法.pdf', 'pdf', '/tmp/labor-law.pdf', 'SUCCESS', 1)
            """
        )
        connection.execute(
            """
            INSERT INTO chunk (document_id, chunk_no, content, vector_key)
            VALUES (1, 1, '解除劳动合同应符合法定条件。', 'chunk:1')
            """
        )


def _service(directory: str, *, score: float = 0.82):
    database_path = Path(directory) / "test.db"
    _create_database(database_path)
    config = Settings(
        database_url=f"sqlite:///{database_path}",
        llm_api_key="test-key",
        llm_base_url="https://llm.example.test/v1",
        llm_model="test-model",
    )
    session_service = SessionService(database_path=database_path)
    retrieval = FakeRetrieval(
        [
            {
                "chunk_id": 1,
                "document_id": 1,
                "file_name": "劳动合同法.pdf",
                "chunk_no": 1,
                "content": "解除劳动合同应符合法定条件。",
                "score": score,
                "retrieval_score": score,
                "rerank_score": None,
                "rank_no": 1,
            }
        ]
    )
    llm = FakeLlm()
    service = ChatService(session_service, retrieval, config, llm_client=llm)
    return service, session_service, retrieval, llm


def _events(service: ChatService, session_id: str, request: FakeRequest | None = None):
    payload = ChatRequest(
        session_id=UUID(session_id),
        question="那公司这样解除劳动关系呢？",
        answer_style="plain",
    )
    return asyncio.run(_collect(service.stream_chat(payload, request or FakeRequest())))


async def _collect(stream):
    return [event async for event in stream]


def test_rag_stream_persists_answer_and_only_retrieved_citations() -> None:
    with tempfile.TemporaryDirectory() as directory:
        service, sessions, retrieval, llm = _service(directory)
        session = sessions.create_session()

        events = _events(service, session["id"])

        assert [event.splitlines()[0] for event in events] == [
            "event: token",
            "event: token",
            "event: sources",
            "event: done",
        ]
        assert retrieval.queries == ["那公司这样解除劳动关系呢？"]
        assert len(llm.completions) == 1
        messages = sessions.list_messages(session["id"])
        assert [message["role"] for message in messages] == ["user", "assistant"]
        assert messages[0]["rewritten_question"] == "那公司这样解除劳动关系呢？"
        assert messages[1]["content"] == "应结合具体证据判断。建议保留书面材料。"
        assert messages[1]["citations"][0]["chunk_id"] == 1


def test_low_similarity_evidence_is_refused_without_calling_model() -> None:
    with tempfile.TemporaryDirectory() as directory:
        service, sessions, _, llm = _service(directory, score=0.1)
        session = sessions.create_session()

        events = _events(service, session["id"])

        assert len(events) == 3
        assert events[0].startswith("event: token")
        assert '"items":[]' in events[1]
        assert '"refused":true' in events[2]
        assert llm.completions == []
        messages = sessions.list_messages(session["id"])
        assert messages[-1]["refused"] is True
        assert messages[-1]["citations"] == []


def test_recent_session_turns_are_used_to_rewrite_the_retrieval_query() -> None:
    with tempfile.TemporaryDirectory() as directory:
        service, sessions, retrieval, llm = _service(directory)
        session = sessions.create_session()
        sessions.create_user_message(session["id"], "试用期被辞退有补偿吗？")
        sessions.persist_assistant(
            session["id"], "要看解除理由和证据。", "plain", False, []
        )

        _events(service, session["id"])

        assert retrieval.queries == ["那公司以不符合录用条件解除劳动关系是否合法？"]
        assert len(llm.completions) == 2
        latest_user = sessions.list_messages(session["id"])[2]
        assert latest_user["rewritten_question"] == retrieval.queries[0]
        rewrite_payload = llm.completions[0][0][1]["content"]
        assert "试用期被辞退有补偿吗？" in rewrite_payload


def test_index_not_ready_returns_terminal_error_and_keeps_user_message() -> None:
    with tempfile.TemporaryDirectory() as directory:
        service, sessions, retrieval, _ = _service(directory)
        retrieval.error = VectorStoreNotInitialized("not ready")
        session = sessions.create_session()

        events = _events(service, session["id"])

        assert len(events) == 1
        assert events[0].startswith("event: error")
        assert '"code":50301' in events[0]
        assert [
            message["role"] for message in sessions.list_messages(session["id"])
        ] == ["user"]


def test_client_disconnect_does_not_persist_partial_assistant_message() -> None:
    with tempfile.TemporaryDirectory() as directory:
        service, sessions, _, _ = _service(directory)
        session = sessions.create_session()

        events = _events(
            service,
            session["id"],
            FakeRequest(disconnected=[False, False, True]),
        )

        assert len(events) == 1
        assert events[0].startswith("event: token")
        assert [
            message["role"] for message in sessions.list_messages(session["id"])
        ] == ["user"]


def test_empty_model_stream_emits_a_terminal_error() -> None:
    with tempfile.TemporaryDirectory() as directory:
        service, sessions, _, _ = _service(directory)
        service.llm_client = EmptyStreamLlm()
        session = sessions.create_session()

        events = _events(service, session["id"])

        assert len(events) == 1
        assert events[0].startswith("event: error")
        assert '"code":50302' in events[0]
        assert [
            message["role"] for message in sessions.list_messages(session["id"])
        ] == ["user"]
