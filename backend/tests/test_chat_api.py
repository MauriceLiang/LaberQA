import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.dependencies import get_chat_service
from app.core.config import Settings, settings
from app.main import app
from app.services.chat_service import ChatService
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
