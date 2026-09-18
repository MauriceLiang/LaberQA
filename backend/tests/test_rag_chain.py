import asyncio
import json
from typing import Any

from app.core.config import Settings
from app.schemas.contracts import AnswerStyle
from app.services.rag_chain import REFUSAL_TEXT, RagChain
from app.services.retrieval import LaborKnowledgeRetriever


class FakeRetrieval:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def retrieve(self, query: str) -> list[dict[str, Any]]:
        self.queries.append(query)
        return [
            {
                "chunk_id": 7,
                "document_id": 3,
                "file_name": "劳动合同法.pdf",
                "chunk_no": 4,
                "content": "建立劳动关系后，应当订立书面劳动合同。",
                "score": 0.91,
                "retrieval_score": 0.91,
                "rerank_score": None,
                "rank_no": 1,
            }
        ]


class FakeLlm:
    def __init__(self) -> None:
        self.completions: list[tuple[list[dict[str, str]], bool]] = []

    async def complete(
        self, messages: list[dict[str, str]], *, json_mode: bool = False
    ) -> str:
        self.completions.append((messages, json_mode))
        if json_mode:
            payload = json.loads(messages[-1]["content"])
            assert payload["question"] == "劳动合同需要签订吗？"
            return '{"sufficient":true,"reason":"evidence supports the answer"}'
        return "请根据材料判断。"

    async def stream(self, messages: list[dict[str, str]]):
        assert messages[-1]["role"] == "user"
        yield "请根据"
        yield "材料判断。"


def _config() -> Settings:
    return Settings(
        database_url="sqlite:////tmp/rag-chain-test.db",
        llm_api_key="test-key",
        llm_base_url="https://llm.example.test/v1",
        llm_model="test-model",
    )


def test_langchain_retriever_preserves_source_metadata() -> None:
    retrieval = FakeRetrieval()
    retriever = LaborKnowledgeRetriever(retrieval_service=retrieval)

    documents = asyncio.run(retriever.ainvoke("劳动合同需要签订吗？"))

    assert retrieval.queries == ["劳动合同需要签订吗？"]
    assert len(documents) == 1
    assert documents[0].page_content == "建立劳动关系后，应当订立书面劳动合同。"
    assert documents[0].metadata == {
        "chunk_id": 7,
        "document_id": 3,
        "file_name": "劳动合同法.pdf",
        "chunk_no": 4,
        "score": 0.91,
        "retrieval_score": 0.91,
        "rerank_score": None,
        "rank_no": 1,
    }


def test_rag_chain_uses_prompt_runnable_and_preserves_evidence_text() -> None:
    llm = FakeLlm()
    chain = RagChain(FakeRetrieval(), llm, _config())  # type: ignore[arg-type]
    evidence = [
        {
            "chunk_id": 7,
            "document_id": 3,
            "file_name": "劳动合同法.pdf",
            "chunk_no": 4,
            "content": "<条文> & {花括号}",
            "score": 0.91,
            "retrieval_score": 0.91,
            "rerank_score": None,
            "rank_no": 1,
        }
    ]

    answer = asyncio.run(
        chain.complete_answer(
            AnswerStyle.PLAIN,
            "劳动合同需要签订吗？",
            "劳动合同需要签订吗？",
            evidence,
            False,
            None,
        )
    )
    tokens = asyncio.run(
        _collect(
            chain.stream_answer(
                AnswerStyle.PLAIN,
                "劳动合同需要签订吗？",
                "劳动合同需要签订吗？",
                evidence,
                False,
                None,
            )
        )
    )

    assert answer == "请根据材料判断。"
    assert tokens == ["请根据", "材料判断。"]
    rendered_system_prompt = llm.completions[-1][0][0]["content"]
    assert "<条文> & {花括号}" in rendered_system_prompt


def test_evidence_judge_is_a_langchain_prompt_chain() -> None:
    llm = FakeLlm()
    chain = RagChain(FakeRetrieval(), llm, _config())  # type: ignore[arg-type]
    evidence = [
        {
            "chunk_id": 7,
            "document_id": 3,
            "file_name": "劳动合同法.pdf",
            "chunk_no": 4,
            "content": "建立劳动关系后，应当订立书面劳动合同。",
            "score": 0.91,
            "retrieval_score": 0.91,
            "rerank_score": None,
            "rank_no": 1,
        }
    ]

    refused, reason = asyncio.run(
        chain.judge_evidence("劳动合同需要签订吗？", evidence, strict=True)
    )

    assert refused is False
    assert reason is None
    assert llm.completions[-1][1] is True


def test_runnable_branch_returns_fixed_refusal_without_calling_answer_model() -> None:
    llm = FakeLlm()
    chain = RagChain(FakeRetrieval(), llm, _config())  # type: ignore[arg-type]

    answer = asyncio.run(
        chain.complete_answer(
            AnswerStyle.PLAIN,
            "劳动合同需要签订吗？",
            "劳动合同需要签订吗？",
            [],
            False,
            None,
            refused=True,
        )
    )
    tokens = asyncio.run(
        _collect(
            chain.stream_answer(
                AnswerStyle.PLAIN,
                "劳动合同需要签订吗？",
                "劳动合同需要签订吗？",
                [],
                False,
                None,
                refused=True,
            )
        )
    )

    assert answer == REFUSAL_TEXT
    assert tokens == [REFUSAL_TEXT]
    assert llm.completions == []


async def _collect(stream: Any) -> list[str]:
    return [token async for token in stream]
