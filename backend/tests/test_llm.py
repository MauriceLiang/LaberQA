import asyncio
import json

import httpx
import pytest

from app.core.config import Settings
from app.services.llm import LlmClient, ModelUnavailableError


def test_llm_client_reads_openai_compatible_completion_and_sse_tokens() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if json.loads(request.content).get("stream") is True:
            return httpx.Response(
                200,
                text=(
                    'data: {"choices":[{"delta":{"content":"答"}}]}\n\n'
                    'data: {"choices":[{"delta":{"content":"案"}}]}\n\n'
                    "data: [DONE]\n\n"
                ),
            )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "检索问题"}}]},
        )

    async def exercise() -> list[str]:
        config = Settings(
            llm_api_key="test-key",
            llm_base_url="https://llm.example.test/v1",
            llm_model="test-model",
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            llm = LlmClient(config, client=client)
            completion = await llm.complete([{"role": "user", "content": "rewrite"}])
            tokens = [
                token
                async for token in llm.stream([{"role": "user", "content": "answer"}])
            ]
            assert completion == "检索问题"
            return tokens

    assert asyncio.run(exercise()) == ["答", "案"]
    assert [request.url.path for request in requests] == [
        "/v1/chat/completions",
        "/v1/chat/completions",
    ]
    assert all(
        request.headers["authorization"] == "Bearer test-key" for request in requests
    )


def test_llm_client_requires_all_runtime_configuration() -> None:
    llm = LlmClient(Settings())

    with pytest.raises(ModelUnavailableError):
        asyncio.run(llm.complete([{"role": "user", "content": "test"}]))


def test_llm_client_rejects_empty_or_error_sse_streams() -> None:
    async def exercise(body: str) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=body)

        config = Settings(
            llm_api_key="test-key",
            llm_base_url="https://llm.example.test/v1",
            llm_model="test-model",
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            llm = LlmClient(config, client=client)
            with pytest.raises(ModelUnavailableError):
                _ = [
                    token
                    async for token in llm.stream(
                        [{"role": "user", "content": "answer"}]
                    )
                ]

    asyncio.run(exercise('data: {"choices":[]}\n\ndata: [DONE]\n\n'))
    asyncio.run(exercise('data: {"error":{"message":"unavailable"}}\n\n'))
    asyncio.run(exercise('data: {"choices":[{"delta":{"content":"部分回答"}}]}\n\n'))
