import re

_HORIZONTAL_WHITESPACE = re.compile(r"[^\S\n]+")
_EXCESSIVE_NEWLINES = re.compile(r"\n{3,}")


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
