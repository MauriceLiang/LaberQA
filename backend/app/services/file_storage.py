"""Safe local storage for uploaded source documents."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from uuid import uuid4

from app.core.error_codes import ErrorCode

DEFAULT_MAX_UPLOAD_SIZE_BYTES = 20 * 1024 * 1024
_MIME_TYPES_BY_SUFFIX = {
    ".pdf": frozenset({"application/pdf"}),
    ".doc": frozenset({"application/msword", "application/vnd.ms-word"}),
    ".docx": frozenset(
        {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    ),
    ".txt": frozenset({"text/plain"}),
}
_READ_CHUNK_SIZE = 64 * 1024


class FileProcessingError(Exception):
    """Base exception for upload and document parsing errors."""


class UploadValidationError(FileProcessingError):
    """Upload validation error with the API code and status for its caller."""

    def __init__(self, message: str, code: ErrorCode, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status


class UnsupportedFileTypeError(UploadValidationError):
    """The uploaded file has an unsupported extension."""

    def __init__(self) -> None:
        super().__init__(
            "仅支持 PDF、DOC、DOCX 和 TXT 文件",
            ErrorCode.UNSUPPORTED_FILE_TYPE,
            400,
        )


class InvalidFileMimeTypeError(UploadValidationError):
    """The uploaded MIME type does not match its extension."""

    def __init__(self) -> None:
        super().__init__("文件 MIME 类型与扩展名不匹配", ErrorCode.INVALID_REQUEST, 400)


class FileTooLargeError(UploadValidationError):
    """The uploaded file exceeds the configured limit."""

    def __init__(self, max_size_bytes: int) -> None:
        super().__init__(
            f"文件超过大小限制（{max_size_bytes} 字节）",
            ErrorCode.FILE_TOO_LARGE,
            413,
        )


class EmptyFileError(UploadValidationError):
    """The uploaded file contains no usable content."""

    def __init__(self) -> None:
        super().__init__("上传文件为空", ErrorCode.EMPTY_FILE, 400)


class DocumentConverterUnavailable(FileProcessingError):
    """LibreOffice is not available for legacy DOC conversion."""


class DocumentParseError(FileProcessingError):
    """The source document could not be decoded or parsed."""


@dataclass(frozen=True)
class StoredFile:
    file_name: str
    file_type: str
    path: Path
    size_bytes: int
    mime_type: str


class FileStorage:
    """Validate and atomically persist document uploads under a private name."""

    def __init__(
        self,
        upload_dir: str | Path,
        max_size_bytes: int = DEFAULT_MAX_UPLOAD_SIZE_BYTES,
    ) -> None:
        if max_size_bytes <= 0:
            raise ValueError("max_size_bytes must be positive")
        self.upload_dir = Path(upload_dir).expanduser().resolve()
        self.max_size_bytes = max_size_bytes

    def save(
        self,
        source: BinaryIO,
        filename: str | None,
        content_type: str | None,
    ) -> StoredFile:
        file_name, suffix = self._validated_name(filename)
        mime_type = self._validated_mime_type(suffix, content_type)

        self.upload_dir.mkdir(parents=True, exist_ok=True)
        destination = self.upload_dir / f"{uuid4().hex}{suffix}"
        temporary_path: Path | None = None
        size_bytes = 0

        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".upload-", suffix=".tmp", dir=self.upload_dir
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as output:
                while True:
                    remaining = self.max_size_bytes - size_bytes
                    block = source.read(min(_READ_CHUNK_SIZE, remaining + 1))
                    if not block:
                        break
                    size_bytes += len(block)
                    if size_bytes > self.max_size_bytes:
                        raise FileTooLargeError(self.max_size_bytes)
                    output.write(block)

                if size_bytes == 0:
                    raise EmptyFileError()

                output.flush()
                os.fsync(output.fileno())

            os.replace(temporary_path, destination)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

        return StoredFile(
            file_name=file_name,
            file_type=suffix[1:],
            path=destination,
            size_bytes=size_bytes,
            mime_type=mime_type,
        )

    def delete(self, path: str | Path) -> None:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.upload_dir / candidate
        parent = candidate.parent.resolve()
        if not parent.is_relative_to(self.upload_dir):
            raise ValueError("file path must be inside the upload directory")
        candidate.unlink(missing_ok=True)

    @staticmethod
    def _validated_name(filename: str | None) -> tuple[str, str]:
        # Normalize both separator styles before taking the basename. This also
        # handles Windows client paths when the server is running on POSIX.
        basename = (filename or "").replace("\\", "/").rsplit("/", maxsplit=1)[-1]
        suffix = PurePosixPath(basename).suffix.lower()
        if (
            not basename
            or basename in {".", ".."}
            or suffix not in _MIME_TYPES_BY_SUFFIX
        ):
            raise UnsupportedFileTypeError()
        return basename, suffix

    @staticmethod
    def _validated_mime_type(suffix: str, content_type: str | None) -> str:
        mime_type = (content_type or "").split(";", maxsplit=1)[0].strip().lower()
        if mime_type not in _MIME_TYPES_BY_SUFFIX[suffix]:
            raise InvalidFileMimeTypeError()
        return mime_type
