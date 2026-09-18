"""Behavior baseline for the current LangChain-backed RAG path."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.rag.chains import REFUSAL_TEXT, RagChain
from app.repositories.document_repository import DocumentRepository
from app.schemas.contracts import AnswerStyle
from app.services.retrieval import RetrievalService
from app.services.vector_store import VectorStoreService
from tests.support import AsyncClientChatModel

from .conftest import (
    BASELINE_ANSWER,
    BASELINE_FILE_NAME,
    BASELINE_QUESTION,
    FixedLlm,
    seed_success_document,
)


def _chain(
    database_path: Path,
    config: Settings,
    embedding: Any,
    llm: FixedLlm,
) -> RagChain:
    repository = DocumentRepository(database_path)
    vector_store = VectorStoreService(
        config,
        embedding_service=embedding,
        index_dir=config.faiss_path / "production",
    )
    chunk_id = repository.list_success_chunks()[0]["id"]
    vector_store.add([(chunk_id, [1.0, 0.0])])
    retrieval = RetrievalService(
        config,
        repository=repository,
        embedding_service=embedding,
        vector_store=vector_store,
    )
    return RagChain(retrieval, AsyncClientChatModel(llm), config)


def test_fixed_question_returns_expected_document_and_answer(
    baseline_database: Path,
    baseline_config: Settings,
    baseline_embedding: Any,
) -> None:
    document_id = seed_success_document(baseline_database)
    llm = FixedLlm()
    chain = _chain(baseline_database, baseline_config, baseline_embedding, llm)

    evidence = asyncio.run(chain.retrieve(BASELINE_QUESTION))
    answer = asyncio.run(
        chain.complete_answer(
            AnswerStyle.PLAIN,
            BASELINE_QUESTION,
            BASELINE_QUESTION,
            evidence,
            False,
            None,
        )
    )
    streamed = asyncio.run(
        _collect(
            chain.stream_answer(
                AnswerStyle.PLAIN,
                BASELINE_QUESTION,
                BASELINE_QUESTION,
                evidence,
                False,
                None,
            )
        )
    )

    assert evidence == [
        {
            "chunk_id": 1,
            "document_id": document_id,
            "file_name": BASELINE_FILE_NAME,
            "chunk_no": 1,
            "content": "第十条 建立劳动关系，应当订立书面劳动合同。",
            "score": 1.0,
            "retrieval_score": 1.0,
            "rerank_score": None,
            "rank_no": 1,
        }
    ]
    assert answer == BASELINE_ANSWER
    assert streamed == [
        "根据《劳动合同法》，",
        "用人单位应当订立书面劳动合同。",
    ]
    assert llm.completions and llm.completions[-1][1] is False
    assert llm.streams


def test_refusal_branch_skips_answer_model_for_insufficient_evidence(
    baseline_database: Path,
    baseline_config: Settings,
    baseline_embedding: Any,
) -> None:
    seed_success_document(baseline_database)
    llm = FixedLlm()
    chain = _chain(baseline_database, baseline_config, baseline_embedding, llm)
    weak_evidence = [
        {
            "chunk_id": 1,
            "document_id": 1,
            "file_name": BASELINE_FILE_NAME,
            "chunk_no": 1,
            "content": "无关内容",
            "score": 0.1,
            "retrieval_score": 0.1,
            "rerank_score": None,
            "rank_no": 1,
        }
    ]

    refused, reason = asyncio.run(
        chain.judge_evidence(BASELINE_QUESTION, weak_evidence)
    )
    answer = asyncio.run(
        chain.complete_answer(
            AnswerStyle.PLAIN,
            BASELINE_QUESTION,
            BASELINE_QUESTION,
            weak_evidence,
            False,
            None,
            refused=refused,
        )
    )

    assert refused is True
    assert reason is not None
    assert answer == REFUSAL_TEXT
    assert llm.completions == []


async def _collect(stream: Any) -> list[str]:
    return [token async for token in stream]
