import asyncio
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import Mock
from uuid import UUID

from app.core.config import Settings
from app.schemas.contracts import ChatRequest, MissingKnowledgeQuery
from app.services.chat_service import ChatService
from app.services.compliance import COMPLIANCE_NOTICE
from app.services.missing_knowledge import ExecutionMode, MissingKnowledgeReason
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
        self.streams: list[list[dict[str, str]]] = []

    async def complete(
        self, messages: list[dict[str, str]], *, json_mode: bool = False
    ) -> str:
        self.completions.append((messages, json_mode))
        if json_mode:
            return '{"sufficient":true,"reason":"evidence supports the answer"}'
        return "那公司以不符合录用条件解除劳动关系是否合法？"

    async def stream(self, messages: list[dict[str, str]]):
        self.streams.append(messages)
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


def _events(
    service: ChatService,
    session_id: str,
    request: FakeRequest | None = None,
    *,
    question: str = "那公司这样解除劳动关系呢？",
    answer_style: str = "plain",
    execution_mode: ExecutionMode = ExecutionMode.PRODUCTION,
):
    payload = ChatRequest(
        session_id=UUID(session_id),
        question=question,
        answer_style=answer_style,
    )
    return asyncio.run(
        _collect(
            service.stream_chat(
                payload, request or FakeRequest(), execution_mode=execution_mode
            )
        )
    )


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
        record = Mock(wraps=service.missing_knowledge_service.record_refusal)
        service.missing_knowledge_service.record_refusal = record
        session = sessions.create_session()

        events = _events(service, session["id"])

        assert len(events) == 3
        assert events[0].startswith("event: token")
        assert '"items":[]' in events[1]
        assert '"refused":true' in events[2]
        assert llm.completions == []
        rows, total = service.missing_knowledge_service.list(MissingKnowledgeQuery())
        assert total == 1
        assert rows[0]["topic_key"] == "termination"
        assert rows[0]["count"] == 1
        assert record.call_args.args[1] is MissingKnowledgeReason.LOW_RELEVANCE
        messages = sessions.list_messages(session["id"])
        assert messages[-1]["refused"] is True
        assert messages[-1]["citations"] == []


def test_empty_retrieval_result_is_recorded_with_its_evidence_reason() -> None:
    with tempfile.TemporaryDirectory() as directory:
        service, sessions, retrieval, _ = _service(directory)
        retrieval.evidence = []
        record = Mock(wraps=service.missing_knowledge_service.record_refusal)
        service.missing_knowledge_service.record_refusal = record
        session = sessions.create_session()

        _events(service, session["id"], question="劳动关系解除后能否获得补偿？")

        assert record.call_args.args[1].value == "NO_RETRIEVAL_RESULT"


def test_insufficient_evidence_judgement_is_recorded() -> None:
    class InsufficientJudge(FakeLlm):
        async def complete(
            self, messages: list[dict[str, str]], *, json_mode: bool = False
        ) -> str:
            return '{"sufficient":false,"reason":"not supported"}'

    with tempfile.TemporaryDirectory() as directory:
        service, sessions, _, _ = _service(directory)
        service.llm_client = InsufficientJudge()
        record = Mock(wraps=service.missing_knowledge_service.record_refusal)
        service.missing_knowledge_service.record_refusal = record
        session = sessions.create_session()

        _events(service, session["id"], question="劳动关系解除后能否获得补偿？")

        assert record.call_args.args[1].value == "INSUFFICIENT_EVIDENCE"


def test_failure_to_record_does_not_break_refusal_stream() -> None:
    with tempfile.TemporaryDirectory() as directory:
        service, sessions, _, _ = _service(directory, score=0.1)
        session = sessions.create_session()

        def fail_record(*_args, **_kwargs):
            raise RuntimeError("database unavailable")

        service.missing_knowledge_service.record_refusal = fail_record
        events = _events(service, session["id"])

        assert events[0].startswith("event: token")
        assert '"refused":true' in events[-1]


def test_evidence_judge_failure_refuses_without_recording_missing_knowledge() -> None:
    class BrokenJudge(FakeLlm):
        async def complete(
            self, messages: list[dict[str, str]], *, json_mode: bool = False
        ) -> str:
            raise RuntimeError("judge unavailable")

    with tempfile.TemporaryDirectory() as directory:
        service, sessions, _, _ = _service(directory)
        service.llm_client = BrokenJudge()
        session = sessions.create_session()

        events = _events(service, session["id"])
        rows, total = service.missing_knowledge_service.list(MissingKnowledgeQuery())

        assert '"refused":true' in events[-1]
        assert total == 0
        assert rows == []


def test_non_production_refusal_does_not_record_missing_knowledge() -> None:
    for mode in (ExecutionMode.EVALUATION, ExecutionMode.EXPERIMENT):
        with tempfile.TemporaryDirectory() as directory:
            service, sessions, _, _ = _service(directory, score=0.1)
            session = sessions.create_session()

            try:
                _events(service, session["id"], execution_mode=mode)
            except ValueError as error:
                assert str(error) == "stream_chat only supports PRODUCTION mode"
            else:
                raise AssertionError(
                    "Expected non-production stream mode to be rejected"
                )
            _, total = service.missing_knowledge_service.list(MissingKnowledgeQuery())

            assert total == 0
            assert sessions.list_messages(session["id"]) == []


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


def test_material_request_emits_tool_before_answer_and_persists_tool_result() -> None:
    with tempfile.TemporaryDirectory() as directory:
        service, sessions, _, llm = _service(directory)
        session = sessions.create_session()

        events = _events(
            service,
            session["id"],
            question="公司拖欠工资，我应该准备什么材料？",
        )

        assert [event.splitlines()[0] for event in events] == [
            "event: tool",
            "event: token",
            "event: token",
            "event: sources",
            "event: done",
        ]
        tool_event = json.loads(events[0].splitlines()[1][6:])
        assert tool_event["tool_name"] == "generate_rights_material_checklist"
        assert tool_event["input"] == {
            "dispute_type": "欠薪",
            "description": "公司拖欠工资，我应该准备什么材料？",
        }
        assert tool_event["output"]["materials"] == [
            "劳动合同或能够证明劳动关系的材料",
            "工资条、银行流水等工资支付记录",
            "考勤、排班或工作记录",
            "与用人单位沟通欠薪问题的记录",
        ]
        assert "工资条、银行流水等工资支付记录" in llm.streams[0][0]["content"]
        assistant = sessions.list_messages(session["id"])[-1]
        assert assistant["tool_executions"] == [tool_event]


def test_tool_failure_emits_only_terminal_error_without_fabricated_result() -> None:
    with tempfile.TemporaryDirectory() as directory:
        service, sessions, _, _ = _service(directory)
        session = sessions.create_session()

        def fail_tool(_payload):
            raise RuntimeError("tool unavailable")

        service.material_checklist_tool.execute = fail_tool
        events = _events(
            service,
            session["id"],
            question="公司拖欠工资，我应该准备什么材料？",
        )

        assert len(events) == 1
        assert events[0].startswith("event: error")
        assert '"message":"材料清单生成失败"' in events[0]
        assert [
            message["role"] for message in sessions.list_messages(session["id"])
        ] == ["user"]


def test_material_checklist_is_not_run_when_evidence_gate_refuses():
    with tempfile.TemporaryDirectory() as directory:
        service, sessions, _, _ = _service(directory, score=0.1)
        session = sessions.create_session()

        events = _events(
            service,
            session["id"],
            question="公司拖欠工资，我应该准备什么材料？",
        )

        assert [event.splitlines()[0] for event in events] == [
            "event: token",
            "event: sources",
            "event: done",
        ]
        assert sessions.list_messages(session["id"])[-1]["tool_executions"] == []


def test_compliance_notice_is_forced_for_both_styles_without_changing_sources():
    outputs = []
    for answer_style in ("plain", "legal"):
        with tempfile.TemporaryDirectory() as directory:
            service, sessions, retrieval, llm = _service(directory)
            session = sessions.create_session()
            events = _events(
                service,
                session["id"],
                question="劳动仲裁的申请期限是多久？",
                answer_style=answer_style,
            )
            response = sessions.list_messages(session["id"])[-1]
            prompt = llm.streams[0][0]["content"]
            sources_event = next(
                event for event in events if event.startswith("event: sources")
            )
            sources = json.loads(sources_event.splitlines()[1][6:])
            outputs.append((response, sources, retrieval.queries, prompt))

            assert COMPLIANCE_NOTICE in response["content"]
            assert "需要合规提示：true" in prompt
            assert COMPLIANCE_NOTICE in prompt

    assert outputs[0][1] == outputs[1][1]
    assert outputs[0][2] == outputs[1][2]
    assert outputs[0][0]["citations"] == outputs[1][0]["citations"]
    assert "面向普通劳动者" in outputs[0][3]
    assert "严谨、客观" in outputs[1][3]


def test_concrete_route_in_final_answer_adds_notice_even_if_question_did_not():
    class RouteAnswerLlm(FakeLlm):
        async def stream(self, messages: list[dict[str, str]]):
            self.streams.append(messages)
            yield "可以向当地劳动监察部门投诉。"

    with tempfile.TemporaryDirectory() as directory:
        service, sessions, _, _ = _service(directory)
        llm = RouteAnswerLlm()
        service.llm_client = llm
        session = sessions.create_session()

        events = _events(service, session["id"], question="我现在应该如何处理？")

        assistant = sessions.list_messages(session["id"])[-1]
        assert COMPLIANCE_NOTICE in assistant["content"]
        assert events[-3].startswith("event: token")


def test_compliance_notice_is_not_triggered_by_retrieved_evidence_alone():
    with tempfile.TemporaryDirectory() as directory:
        service, sessions, retrieval, llm = _service(directory)
        retrieval.evidence[0]["content"] = "可以向当地劳动监察部门了解情况。"
        session = sessions.create_session()

        _events(service, session["id"], question="我应该如何保存工资记录？")

        assistant = sessions.list_messages(session["id"])[-1]
        prompt = llm.streams[0][0]["content"]
        assert COMPLIANCE_NOTICE not in assistant["content"]
        assert "需要合规提示：false" in prompt
