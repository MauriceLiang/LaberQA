"""Text extraction for supported source-document formats."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from app.core.config import Settings, settings
from app.services.file_storage import (
    DocumentConverterUnavailable,
    DocumentParseError,
    EmptyFileError,
    UnsupportedFileTypeError,
)

_CONVERTER_TIMEOUT_SECONDS = 120


def find_doc_converter(preferred: str | None = None) -> str | None:
    return (
        shutil.which(preferred or settings.doc_converter)
        or shutil.which("soffice")
        or shutil.which("libreoffice")
    )


def package_doc_parser_available() -> bool:
    """Return whether the bundled pure-Python legacy DOC parser is importable."""
    try:
        from doc2docx import convert
    except ImportError:
        return False
    return callable(convert)


def is_doc_parser_available(config: Settings | None = None) -> bool:
    """Return whether the configured DOC parser or its fallback is available."""
    parser_backend = getattr(config or settings, "doc_parser_backend", "package")
    if parser_backend == "package" and package_doc_parser_available():
        return True
    return (
        find_doc_converter(getattr(config or settings, "doc_converter", None))
        is not None
    )


class ParserFactory:
    """Parse PDF, DOCX, TXT, and legacy DOC documents into plain text."""

    @classmethod
    def parse(
        cls,
        path: str | Path,
        file_type: str,
        *,
        config: Settings | None = None,
    ) -> str:
        source_path = Path(path)
        normalized_type = str(getattr(file_type, "value", file_type))
        normalized_type = normalized_type.lower().lstrip(".")
        if normalized_type not in {"pdf", "doc", "docx", "txt"}:
            raise UnsupportedFileTypeError()

        suffix = source_path.suffix.lower().lstrip(".")
        if suffix and suffix != normalized_type:
            raise UnsupportedFileTypeError()

        try:
            if source_path.stat().st_size == 0:
                raise EmptyFileError()
        except OSError as exc:
            raise DocumentParseError("无法读取文档文件") from exc

        if normalized_type == "pdf":
            return cls._parse_pdf(source_path)
        if normalized_type == "docx":
            return cls._parse_docx(source_path)
        if normalized_type == "txt":
            return cls._parse_txt(source_path)
        return cls._parse_doc(source_path, config=config)

    @staticmethod
    def _parse_txt(path: Path) -> str:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentParseError("TXT 文件不是有效的 UTF-8 文本") from exc
        except OSError as exc:
            raise DocumentParseError("无法读取 TXT 文件") from exc
        if not text.strip():
            raise EmptyFileError()
        return text

    @staticmethod
    def _parse_pdf(path: Path) -> str:
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:
            if isinstance(exc, DocumentParseError):
                raise
            raise DocumentParseError("PDF 文件解析失败") from exc
        if not text.strip():
            raise DocumentParseError("PDF 未提取到可复制文本")
        return text

    @staticmethod
    def _parse_docx(path: Path) -> str:
        try:
            from docx import Document
            from docx.table import Table
            from docx.text.paragraph import Paragraph

            document = Document(str(path))
            blocks: list[str] = []
            for block in document.iter_inner_content():
                if isinstance(block, Paragraph):
                    blocks.append(block.text)
                elif isinstance(block, Table):
                    for row in block.rows:
                        blocks.append("\t".join(cell.text for cell in row.cells))
            text = "\n".join(blocks)
        except Exception as exc:
            if isinstance(exc, DocumentParseError):
                raise
            raise DocumentParseError("DOCX 文件解析失败") from exc
        if not text.strip():
            raise EmptyFileError()
        return text

    @classmethod
    def _parse_doc(
        cls,
        path: Path,
        *,
        config: Settings | None = None,
    ) -> str:
        parser_config = config or settings
        if (
            parser_config.doc_parser_backend == "package"
            and package_doc_parser_available()
        ):
            return cls._parse_doc_with_package(path)
        return cls._parse_doc_with_libreoffice(path, parser_config.doc_converter)

    @classmethod
    def _parse_doc_with_package(cls, path: Path) -> str:
        try:
            from doc2docx import convert
        except Exception as exc:
            raise DocumentConverterUnavailable("msdoc2docx 未安装或不可用") from exc

        try:
            with tempfile.TemporaryDirectory(
                prefix="laberqa-doc-convert-"
            ) as directory:
                converted_path = Path(directory) / "converted.docx"
                result = convert(path, converted_path)
                if cls._conversion_report_has_errors(result):
                    raise DocumentParseError("DOC 转换报告包含错误")
                if not converted_path.is_file():
                    raise DocumentParseError("DOC 转换器未生成 DOCX 文件")
                return cls._parse_docx(converted_path)
        except DocumentParseError:
            raise
        except Exception as exc:
            raise DocumentParseError("DOC 转换失败") from exc

    @staticmethod
    def _conversion_report_has_errors(result: object) -> bool:
        report = getattr(result, "report", None)
        diagnostics = getattr(report, "diagnostics", ())
        for diagnostic in diagnostics:
            severity = getattr(diagnostic, "severity", diagnostic)
            severity_value = getattr(severity, "value", severity)
            if str(severity_value).lower() == "error":
                return True
        return False

    @classmethod
    def _parse_doc_with_libreoffice(
        cls, path: Path, preferred: str | None = None
    ) -> str:
        converter = find_doc_converter(preferred)
        if converter is None:
            raise DocumentConverterUnavailable("DOC 解析器未安装或不可用")

        try:
            with tempfile.TemporaryDirectory(
                prefix="laberqa-doc-convert-"
            ) as directory:
                temporary_directory = Path(directory)
                user_profile = temporary_directory / "profile"
                user_profile.mkdir()
                command = [
                    converter,
                    f"-env:UserInstallation={user_profile.as_uri()}",
                    "--headless",
                    "--convert-to",
                    "docx",
                    "--outdir",
                    str(temporary_directory),
                    str(path),
                ]
                subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=_CONVERTER_TIMEOUT_SECONDS,
                )
                converted_path = temporary_directory / f"{path.stem}.docx"
                if not converted_path.is_file():
                    raise DocumentParseError("DOC 转换器未生成 DOCX 文件")
                return cls._parse_docx(converted_path)
        except DocumentConverterUnavailable:
            raise
        except DocumentParseError:
            raise
        except FileNotFoundError as exc:
            raise DocumentConverterUnavailable("LibreOffice 不可用") from exc
        except subprocess.TimeoutExpired as exc:
            raise DocumentParseError("DOC 转换超时") from exc
        except subprocess.CalledProcessError as exc:
            raise DocumentParseError("DOC 转换失败") from exc
        except OSError as exc:
            raise DocumentParseError("DOC 转换失败") from exc
