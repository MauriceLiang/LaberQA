import re
from dataclasses import dataclass

_HORIZONTAL_WHITESPACE = re.compile(r"[^\S\n]+")
_EXCESSIVE_NEWLINES = re.compile(r"\n{3,}")


@dataclass(frozen=True, slots=True)
class TextChunk:
    chunk_no: int
    content: str


class TextCleaner:
    @staticmethod
    def clean(text: str) -> str:
        """Normalize whitespace while preserving all non-whitespace characters."""
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = [
            _HORIZONTAL_WHITESPACE.sub(" ", line).strip()
            for line in normalized.split("\n")
        ]
        normalized = "\n".join(lines)
        normalized = _EXCESSIVE_NEWLINES.sub("\n\n", normalized)
        return normalized.strip()


class TextChunker:
    def __init__(self, chunk_size: int = 600, chunk_overlap: int = 100) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        from app.rag.splitters import LegalTextSplitter

        self._splitter = LegalTextSplitter(chunk_size, chunk_overlap)

    def chunk(self, text: str) -> list[TextChunk]:
        return [
            TextChunk(chunk_no=index, content=content)
            for index, content in enumerate(self._splitter.split_text(text), start=1)
        ]
