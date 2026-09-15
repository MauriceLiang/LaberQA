import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.dependencies import get_chat_service
from app.core.config import Settings, settings
from app.core.database import initialize_database
from app.main import app
from app.services.chat_service import ChatService
from app.services.missing_knowledge import MissingKnowledgeReason
from app.services.session_service import SessionService
from app.services.vector_store import VectorStoreNotInitialized


class UnreadyRetrieval:
    def retrieve(self, query: str) -> list[dict]:
        raise VectorStoreNotInitialized("not ready")


def test_session_and_chat_routes_use_the_frozen_contract_in_process() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database_path = Path(directory) / "api.db"
        original_values = (
            settings.database_url,
            settings.faiss_dir,
            settings.upload_dir,
        )
        settings.database_url = f"sqlite:///{database_path}"
        settings.faiss_dir = Path(directory) / "faiss"
        settings.upload_dir = Path(directory) / "uploads"
        config = Settings(
            database_url=f"sqlite:///{database_path}",
            llm_api_key="",
            llm_base_url="",
            llm_model="",
        )
        chat_service = ChatService(
            SessionService(database_path=database_path),
            UnreadyRetrieval(),
            config,
        )
        app.dependency_overrides[get_chat_service] = lambda: chat_service

        try:
            with TestClient(app) as client:
                created = client.post("/api/sessions", json={"title": None})
                session_id = created.json()["data"]["id"]

                chat = client.post(
                    "/api/chat/stream",
                    json={
                        "session_id": session_id,
                        "question": "拖欠工资应该怎么办？",
                        "answer_style": "plain",
                    },
                )
                messages = client.get(f"/api/sessions/{session_id}/messages")
                missing = client.get(
                    "/api/sessions/00000000-0000-0000-0000-000000000000/messages"
                )

            assert created.status_code == 201
            assert created.json()["data"]["id"] == session_id
            assert chat.status_code == 200
            assert chat.headers["content-type"].startswith("text/event-stream")
            assert chat.text.startswith('event: error\ndata: {"code":50301')
            assert messages.json()["data"][0]["role"] == "user"
            assert messages.json()["data"][0]["content"] == "拖欠工资应该怎么办？"
            assert missing.status_code == 404
            assert missing.json()["code"] == 40402
        finally:
            app.dependency_overrides.pop(get_chat_service, None)
            (
                settings.database_url,
                settings.faiss_dir,
                settings.upload_dir,
            ) = original_values


def test_material_checklist_route_returns_shared_tool_execution_contract() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database_path = Path(directory) / "tool-api.db"
        chat_service = ChatService(
            SessionService(database_path=database_path),
            UnreadyRetrieval(),
            Settings(
                database_url=f"sqlite:///{database_path}",
                llm_api_key="",
                llm_base_url="",
                llm_model="",
            ),
        )
        app.dependency_overrides[get_chat_service] = lambda: chat_service

        try:
            with TestClient(app) as client:
                response = client.post(
                    "/api/tools/material-checklist",
                    json={
                        "dispute_type": "欠薪",
                        "description": "单位连续两个月未支付工资",
                    },
                )
        finally:
            app.dependency_overrides.pop(get_chat_service, None)

        assert response.status_code == 200
        assert response.json() == {
            "code": 0,
            "message": "success",
            "data": {
                "tool_name": "generate_rights_material_checklist",
                "input": {
                    "dispute_type": "欠薪",
                    "description": "单位连续两个月未支付工资",
                },
                "output": {
                    "materials": [
                        "劳动合同或能够证明劳动关系的材料",
                        "工资条、银行流水等工资支付记录",
                        "考勤、排班或工作记录",
                        "与用人单位沟通欠薪问题的记录",
                    ],
                    "note": "材料清单仅用于信息整理，具体以实际争议和受理机构要求为准。",
                },
            },
        }
        tool_responses = app.openapi()["paths"]["/api/tools/material-checklist"][
            "post"
        ]["responses"]
        assert "501" not in tool_responses


def test_missing_knowledge_routes_list_filter_and_update_records() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database_path = Path(directory) / "missing-api.db"
        original_values = (
            settings.database_url,
            settings.faiss_dir,
            settings.upload_dir,
        )
        settings.database_url = f"sqlite:///{database_path}"
        settings.faiss_dir = Path(directory) / "faiss"
        settings.upload_dir = Path(directory) / "uploads"
        initialize_database()
        chat_service = ChatService(
            SessionService(database_path=database_path),
            UnreadyRetrieval(),
            Settings(database_url=f"sqlite:///{database_path}"),
        )
        chat_service.missing_knowledge_service.record_refusal(
            "单位拖欠工资怎么办？", MissingKnowledgeReason.NO_RETRIEVAL_RESULT
        )
        app.dependency_overrides[get_chat_service] = lambda: chat_service

        try:
            with TestClient(app) as client:
                pending = client.get(
                    "/api/missing-knowledge",
                    params={
                        "status": "PENDING",
                        "keyword": "工资",
                        "sort": "count_desc",
                    },
                )
                updated = client.patch(
                    "/api/missing-knowledge/1",
                    json={"status": "RESOLVED", "note": "补充工资支付资料"},
                )
                resolved = client.get(
                    "/api/missing-knowledge", params={"status": "RESOLVED"}
                )
                missing = client.patch(
                    "/api/missing-knowledge/999",
                    json={"status": "IGNORED", "note": None},
                )
        finally:
            app.dependency_overrides.pop(get_chat_service, None)
            (
                settings.database_url,
                settings.faiss_dir,
                settings.upload_dir,
            ) = original_values

        assert pending.status_code == 200
        assert pending.json()["data"]["total"] == 1
        assert pending.json()["data"]["items"][0]["topic_key"] == "wage_payment"
        assert updated.status_code == 200
        assert updated.json()["data"]["note"] == "补充工资支付资料"
        assert resolved.json()["data"]["items"][0]["status"] == "RESOLVED"
        assert missing.status_code == 404
        assert missing.json()["code"] == 40405
