from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "劳动权益咨询问答台"
    api_prefix: str = "/api"
    cors_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]
    log_level: str = "INFO"
    database_url: str = "sqlite:///./data/app.db"
    upload_dir: Path = Path("./uploads")
    faiss_dir: Path = Path("./data/faiss")
    max_upload_size_mb: int = Field(default=20, ge=1)
    doc_converter: str = "libreoffice"
    chunk_size: int = Field(default=600, ge=100, le=2000)
    chunk_overlap: int = Field(default=100, ge=0, le=500)
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    embedding_provider: Literal["local", "api"] = "local"
    local_embedding_model: str = "BAAI/bge-small-zh-v1.5"
    local_embedding_device: Literal["auto", "cpu", "cuda", "mps"] = "auto"
    embedding_normalize: bool = True
    embedding_batch_size: int = 32
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_api_model: str = ""

    @model_validator(mode="after")
    def require_api_embedding_settings(self) -> "Settings":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be less than CHUNK_SIZE")
        if self.embedding_provider == "api" and not all(
            (self.embedding_api_key, self.embedding_base_url, self.embedding_api_model)
        ):
            raise ValueError(
                "EMBEDDING_API_KEY, EMBEDDING_BASE_URL and EMBEDDING_API_MODEL "
                "are required when EMBEDDING_PROVIDER=api"
            )
        return self

    @property
    def database_path(self) -> Path:
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            raise ValueError("DATABASE_URL must use SQLite")

        raw_path = self.database_url.removeprefix(prefix)
        if raw_path == ":memory:":
            return Path(raw_path)

        path = Path(raw_path)
        return path if path.is_absolute() else PROJECT_ROOT / path

    @property
    def embedding_model(self) -> str:
        return (
            self.local_embedding_model
            if self.embedding_provider == "local"
            else self.embedding_api_model
        )

    @property
    def faiss_path(self) -> Path:
        return self._project_path(self.faiss_dir)

    @property
    def upload_path(self) -> Path:
        return self._project_path(self.upload_dir)

    @staticmethod
    def _project_path(path: Path) -> Path:
        return path if path.is_absolute() else PROJECT_ROOT / path


settings = Settings()
