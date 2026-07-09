from __future__ import annotations

from pathlib import Path

from wait_local_agent import document_parsing
from wait_local_agent.config import Settings
from wait_local_agent.document_parsing import (
    BasicDocumentParser,
    DocumentParser,
    ExtractedDocument,
    parser_for_name,
)
from wait_local_agent.models import KnowledgeDocument, KnowledgeDocumentWrite
from wait_local_agent.store import Store
from wait_local_agent.vector_search import KnowledgeSearchBackend, search_backend_from_settings

SUPPORTED_SUFFIXES = BasicDocumentParser.supported_suffixes
MAX_CHUNK_CHARS = 900


class KnowledgeIngestionService:
    def __init__(
        self,
        store: Store,
        allowed_root: Path,
        *,
        parser: DocumentParser | None = None,
        search_backend: KnowledgeSearchBackend | None = None,
    ) -> None:
        self.store = store
        self.allowed_root = allowed_root.resolve()
        self.parser = parser or BasicDocumentParser()
        self.search_backend = search_backend

    def ingest_path(self, path: Path, *, client_id: str | None = None) -> list[KnowledgeDocument]:
        target = path.resolve()
        self._validate_allowed_path(target)
        files = self._document_files(target)
        pending_documents = self._prepare_documents(files)
        documents = self.store.upsert_knowledge_documents(
            pending_documents,
            client_id=client_id,
        )
        if self.search_backend is not None:
            for document in documents:
                chunks = self.store.list_knowledge_chunks_for_document(document.id)
                self.search_backend.upsert_document_chunks(chunks)
        return documents

    def _prepare_documents(self, files: list[Path]) -> list[KnowledgeDocumentWrite]:
        pending_documents: list[KnowledgeDocumentWrite] = []
        for file_path in files:
            self._validate_allowed_path(file_path.resolve())
            extracted = self.parser.extract(file_path)
            chunks = chunk_text(extracted.text)
            if not chunks:
                raise ValueError(f"{file_path} does not contain extractable text")
            pending_documents.append(
                KnowledgeDocumentWrite(
                    path=str(extracted.path),
                    title=extracted.title,
                    kind=extracted.kind,
                    checksum=extracted.checksum,
                    modified_at=extracted.modified_at,
                    chunks=chunks,
                )
            )
        return pending_documents

    def _validate_allowed_path(self, target: Path) -> None:
        try:
            target.relative_to(self.allowed_root)
        except ValueError as exc:
            message = f"{target} is outside allowed document root {self.allowed_root}"
            raise ValueError(message) from exc

    def _document_files(self, target: Path) -> list[Path]:
        if target.is_file():
            if target.suffix.lower() not in self.parser.supported_suffixes:
                raise ValueError(f"{target} is not a supported document type")
            return [target]
        if not target.is_dir():
            raise ValueError(f"{target} does not exist")
        files: list[Path] = []
        for candidate in sorted(target.rglob("*")):
            if (
                not candidate.is_file()
                or candidate.suffix.lower() not in self.parser.supported_suffixes
            ):
                continue
            self._validate_allowed_path(candidate.resolve())
            files.append(candidate)
        return files


def ingestion_service_from_settings(store: Store, settings: Settings) -> KnowledgeIngestionService:
    parser = parser_for_name(settings.document_parser, allow_ocr=settings.allow_ocr)
    search_backend = search_backend_from_settings(settings, store)
    return KnowledgeIngestionService(
        store,
        settings.allowed_doc_root,
        parser=parser,
        search_backend=search_backend,
    )


def extract_document(path: Path) -> ExtractedDocument:
    return BasicDocumentParser().extract(path)


def extract_pdf_text(path: Path) -> str:
    return document_parsing.extract_pdf_text(path)


def extract_title(text: str, path: Path) -> str:
    return document_parsing.extract_title(text, path)


def chunk_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        normalized = " ".join(paragraph.split())
        if not current:
            current = normalized
        elif len(current) + 2 + len(normalized) <= max_chars:
            current = f"{current}\n\n{normalized}"
        else:
            chunks.append(current)
            current = normalized

        while len(current) > max_chars:
            chunks.append(current[:max_chars].strip())
            current = current[max_chars:].strip()

    if current:
        chunks.append(current)
    return chunks
