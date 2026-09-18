"""Shared deterministic fixtures for the LangChain migration baseline."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.embedding import EmbeddingService

BASELINE_FILE_NAME = "劳动合同法.txt"
BASELINE_TEXT = "第十条 建立劳动关系，应当订立书面劳动合同。"
BASELINE_QUESTION = "建立劳动关系需要签订书面劳动合同吗？"
BASELINE_ANSWER = "根据《劳动合同法》，用人单位应当订立书面劳动合同。"


class FixedEmbeddingProvider:
    """Small deterministic embedding provider with the production interface."""

    name = "local"
    model = "baseline-fixed-embedding"
    normalize_embeddings = True
    dimension = 2

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts or any(not text.strip() for text in texts):
            raise ValueError("embedding input must not be empty")
        return [[1.0, 0.0] for _ in texts]


class FixedLlm:
    """Deterministic async client used by the existing LlmRunnable adapter."""

    def __init__(self) -> None:
        self.completions: list[tuple[list[dict[str, str]], bool]] = []
        self.streams: list[list[dict[str, str]]] = []

    async def complete(
        self, messages: list[dict[str, str]], *, json_mode: bool = False
    ) -> str:
        self.completions.append((messages, json_mode))
        if json_mode:
            return '{"sufficient":true,"reason":"fixed evidence supports answer"}'
        return BASELINE_ANSWER

    async def stream(
        self, messages: list[dict[str, str]]
    ) -> AsyncIterator[str]:
        self.streams.append(messages)
        yield "根据《劳动合同法》，"
        yield "用人单位应当订立书面劳动合同。"


@pytest.fixture
def baseline_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "baseline.db"
    schema_path = Path(__file__).parents[2] / "app" / "core" / "schema.sql"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(schema_path.read_text(encoding="utf-8"))
    return database_path


@pytest.fixture
def baseline_config(tmp_path: Path, baseline_database: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{baseline_database}",
        upload_dir=tmp_path / "uploads",
        faiss_dir=tmp_path / "faiss",
        llm_api_key="baseline-key",
        llm_base_url="https://llm.example.test/v1",
        llm_model="baseline-model",
        local_embedding_model="baseline-fixed-embedding",
        rag_top_k=5,
        rag_score_threshold=0.35,
    )


@pytest.fixture
def baseline_embedding(baseline_config: Settings) -> EmbeddingService:
    return EmbeddingService(baseline_config, provider=FixedEmbeddingProvider())


def seed_success_document(database_path: Path) -> int:
    with sqlite3.connect(database_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO document (file_name, file_type, file_path, status, chunk_count)
            VALUES (?, 'txt', '/tmp/baseline.txt', 'SUCCESS', 1)
            """,
            (BASELINE_FILE_NAME,),
        )
        document_id = int(cursor.lastrowid)
        connection.execute(
            """
            INSERT INTO chunk (document_id, chunk_no, content, vector_key)
            VALUES (?, 1, ?, ?)
            """,
            (document_id, BASELINE_TEXT, f"chunk:{document_id}"),
        )
    return document_id
