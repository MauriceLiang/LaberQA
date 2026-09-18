"""LangChain document loaders used by the knowledge-base pipeline."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path

from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document

from app.core.config import Settings, settings
from app.services.document_parser import ParserFactory


class LaborQADocumentLoader(BaseLoader):
    """Load a supported file into one LangChain ``Document``.

    Parsing remains delegated to ``ParserFactory`` so legacy DOC conversion,
    table extraction, and the project's domain-specific error handling stay
    unchanged while the RAG pipeline receives the standard LangChain type.
    """

    def __init__(
        self,
        path: str | Path,
        file_type: str | None = None,
        *,
        config: Settings = settings,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        self.path = Path(path)
        self.file_type = file_type or self.path.suffix.lstrip(".")
        self.config = config
        self.metadata = dict(metadata or {})

    def lazy_load(self) -> Iterator[Document]:
        text = ParserFactory.parse(
            self.path,
            self.file_type,
            config=self.config,
        )
        metadata = {
            "source": str(self.path),
            "file_name": self.path.name,
            "file_type": self.file_type.lower().lstrip("."),
            "page": None,
            **self.metadata,
        }
        yield Document(page_content=text, metadata=metadata)
