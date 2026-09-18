"""Domain-aware LangChain text splitters for labor-law documents."""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Iterable

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.constants import CURRENT_SPLITTER_VERSION
from app.services.text import TextCleaner

_CLAUSE_MARKER = re.compile(
    r"第[〇零一二三四五六七八九十百千万两0-9]+条"
    r"(?:之[〇零一二三四五六七八九十百千万两0-9]+)?"
    r"|[（(][一二三四五六七八九十百千万]+[）)]"
    r"|[一二三四五六七八九十百千万]+、"
    r"|[0-9]+[、.](?![0-9])"
)
_SENTENCE_END = re.compile(r"[。；;！？!?]")
_LEGAL_SEPARATORS = [
    r"(?=第[〇零一二三四五六七八九十百千万两0-9]+条(?:之[〇零一二三四五六七八九十百千万两0-9]+)?)",
    r"(?=[（(][一二三四五六七八九十百千万]+[）)])",
    r"(?=[一二三四五六七八九十百千万]+、)",
    r"(?=[0-9]+[、.](?![0-9]))",
    r"\n\n",
    r"\n",
    "。",
    "；",
    "，",
    "",
]


class LegalTextSplitter(RecursiveCharacterTextSplitter):
    """Recursive splitter that preserves legal clause boundaries when possible."""

    def __init__(self, chunk_size: int = 600, chunk_overlap: int = 100) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be greater than zero")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be between zero and chunk_size - 1")

        super().__init__(
            separators=_LEGAL_SEPARATORS,
            keep_separator="end",
            is_separator_regex=True,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
        )
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.version = CURRENT_SPLITTER_VERSION

    def split_text(self, text: str) -> list[str]:
        cleaned_text = TextCleaner.clean(text)
        if not cleaned_text:
            return []

        clause_boundaries, paragraph_boundaries, sentence_boundaries = (
            self._find_boundaries(cleaned_text)
        )
        chunks: list[str] = []
        content_start = 0
        while content_start < len(cleaned_text):
            chunk_start = max(0, content_start - self.chunk_overlap)
            max_end = min(len(cleaned_text), chunk_start + self.chunk_size)
            end = self._choose_end(
                content_start,
                max_end,
                clause_boundaries,
                paragraph_boundaries,
                sentence_boundaries,
            )
            content = cleaned_text[chunk_start:end].strip()
            if content:
                chunks.append(content)
            content_start = end
        return chunks

    def split_documents(self, documents: Iterable[Document]) -> list[Document]:
        chunks = super().split_documents(documents)
        for chunk_no, chunk in enumerate(chunks, start=1):
            chunk.metadata.setdefault("page", None)
            chunk.metadata["chunk_no"] = chunk_no
        return chunks

    @staticmethod
    def _find_boundaries(text: str) -> tuple[list[int], list[int], list[int]]:
        clause_boundaries: list[int] = []
        for match in _CLAUSE_MARKER.finditer(text):
            start = match.start()
            if start == 0:
                continue

            line_start = text.rfind("\n", 0, start) + 1
            at_line_start = not text[line_start:start].strip()
            follows_clause_punctuation = text[start - 1] in "。；;！？!?"
            if at_line_start or follows_clause_punctuation:
                clause_boundaries.append(start)

        paragraph_boundaries = [match.end() for match in re.finditer(r"\n+", text)]
        sentence_boundaries = [match.end() for match in _SENTENCE_END.finditer(text)]
        return clause_boundaries, paragraph_boundaries, sentence_boundaries

    @staticmethod
    def _choose_end(
        content_start: int,
        max_end: int,
        clause_boundaries: list[int],
        paragraph_boundaries: list[int],
        sentence_boundaries: list[int],
    ) -> int:
        for boundaries in (
            clause_boundaries,
            paragraph_boundaries,
            sentence_boundaries,
        ):
            boundary_index = bisect_right(boundaries, max_end) - 1
            if boundary_index >= 0 and boundaries[boundary_index] > content_start:
                return boundaries[boundary_index]
        return max_end
