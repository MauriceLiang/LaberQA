from unittest.mock import patch

from app.core.config import Settings
from app.rag.providers import build_chat_model, build_embeddings


def test_build_chat_model_maps_existing_openai_compatible_settings() -> None:
    config = Settings(
        _env_file=None,
        llm_api_key="test-key",
        llm_base_url="https://llm.example.test/v1/chat/completions",
        llm_model="test-model",
    )

    model = build_chat_model(config)

    assert model.model_name == "test-model"
    assert model.openai_api_key.get_secret_value() == "test-key"
    assert model.openai_api_base == "https://llm.example.test/v1"
    assert model.streaming is True
    assert model.use_responses_api is False


def test_build_local_embeddings_maps_existing_local_settings() -> None:
    config = Settings(
        _env_file=None,
        embedding_provider="local",
        local_embedding_model="baseline-embedding",
        local_embedding_device="cpu",
        embedding_normalize=False,
        embedding_batch_size=7,
    )

    with patch("langchain_huggingface.HuggingFaceEmbeddings") as constructor:
        embedding = build_embeddings(config)

    constructor.assert_called_once_with(
        model_name="baseline-embedding",
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": False, "batch_size": 7},
    )
    assert embedding is constructor.return_value


def test_build_api_embeddings_maps_existing_openai_compatible_settings() -> None:
    config = Settings(
        _env_file=None,
        embedding_provider="api",
        embedding_api_key="embedding-key",
        embedding_base_url="https://embedding.example.test/v1/embeddings",
        embedding_api_model="embedding-model",
    )

    embedding = build_embeddings(config)

    assert embedding.model == "embedding-model"
    assert embedding.openai_api_key.get_secret_value() == "embedding-key"
    assert embedding.openai_api_base == "https://embedding.example.test/v1"
