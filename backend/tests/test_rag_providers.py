from unittest.mock import patch

from app.core.config import Settings
from app.rag import providers as providers_module
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

    with (
        patch(
            "app.rag.providers._resolve_local_model",
            return_value="/cached/baseline-embedding",
        ),
        patch("app.rag.providers._resolve_local_device", return_value="cpu"),
        patch("app.rag.providers._configure_local_torch_runtime") as configure,
        patch("langchain_huggingface.HuggingFaceEmbeddings") as constructor,
    ):
        embedding = build_embeddings(config)

    configure.assert_called_once_with()
    constructor.assert_called_once_with(
        model_name="/cached/baseline-embedding",
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": False, "batch_size": 7},
    )
    assert embedding is constructor.return_value


def test_build_local_embeddings_resolves_auto_device() -> None:
    config = Settings(
        _env_file=None,
        embedding_provider="local",
        local_embedding_device="auto",
    )

    with (
        patch("app.rag.providers._resolve_local_model", return_value="/cached/model"),
        patch("app.rag.providers._resolve_local_device", return_value="mps") as resolve,
        patch("app.rag.providers._configure_local_torch_runtime"),
        patch("langchain_huggingface.HuggingFaceEmbeddings") as constructor,
    ):
        build_embeddings(config)

    resolve.assert_called_once_with("auto")
    assert constructor.call_args.kwargs["model_kwargs"] == {"device": "mps"}


def test_auto_device_falls_back_to_cpu() -> None:
    with (
        patch("torch.cuda.is_available", return_value=False),
        patch("torch.backends.mps.is_available", return_value=False),
    ):
        assert providers_module._resolve_local_device("auto") == "cpu"


def test_macos_local_runtime_limits_torch_threads() -> None:
    with (
        patch.object(providers_module.sys, "platform", "darwin"),
        patch("torch.set_num_threads") as set_num_threads,
    ):
        providers_module._configure_local_torch_runtime()

    set_num_threads.assert_called_once_with(1)


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
