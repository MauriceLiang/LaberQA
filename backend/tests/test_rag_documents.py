from pathlib import Path

from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.constants import CURRENT_SPLITTER_VERSION
from app.rag.loaders import LaberQADocumentLoader
from app.rag.splitters import LegalTextSplitter


def test_loader_returns_langchain_document_with_standard_metadata(
    tmp_path: Path,
) -> None:
    source = tmp_path / "stored-name.txt"
    source.write_text("第一条  工资应当按时支付。\r\n", encoding="utf-8")
    loader = LaberQADocumentLoader(
        source,
        metadata={"document_id": 7, "file_name": "劳动法.txt"},
    )

    documents = loader.load()

    assert isinstance(loader, BaseLoader)
    assert documents == [
        Document(
            page_content="第一条  工资应当按时支付。\n",
            metadata={
                "document_id": 7,
                "file_name": "劳动法.txt",
                "file_type": "txt",
                "source": str(source),
                "page": None,
            },
        )
    ]


def test_legal_splitter_preserves_clause_boundaries_and_chunk_metadata() -> None:
    splitter = LegalTextSplitter(chunk_size=25, chunk_overlap=0)
    source = Document(
        page_content="第一条 甲乙。\n普通段丙丁戊。第二条 己庚辛壬。",
        metadata={
            "document_id": 9,
            "file_name": "law.txt",
            "file_type": "txt",
            "source": "/tmp/law.txt",
        },
    )

    chunks = splitter.split_documents([source])

    assert isinstance(splitter, RecursiveCharacterTextSplitter)
    assert splitter.version == CURRENT_SPLITTER_VERSION
    assert [chunk.page_content for chunk in chunks] == [
        "第一条 甲乙。\n普通段丙丁戊。",
        "第二条 己庚辛壬。",
    ]
    assert [chunk.metadata["chunk_no"] for chunk in chunks] == [1, 2]
    assert all(chunk.metadata["document_id"] == 9 for chunk in chunks)
    assert all(chunk.metadata["page"] is None for chunk in chunks)
