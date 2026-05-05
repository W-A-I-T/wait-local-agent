from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pypdf import PdfReader

from wait_local_agent.models import KnowledgeDocument
from wait_local_agent.store import Store

SUPPORTED_SUFFIXES = {".md", ".txt", ".pdf"}
MAX_CHUNK_CHARS = 900


@dataclass(frozen=True)
class ExtractedDocument:
    path: Path
    title: str
    kind: str
    text: str
    checksum: str
    modified_at: str


class KnowledgeIngestionService:
    def __init__(self, store: Store, allowed_root: Path) -> None:
        self.store = store
        self.allowed_root = allowed_root.resolve()

    def ingest_path(self, path: Path) -> list[KnowledgeDocument]:
        target = path.resolve()
        self._validate_allowed_path(target)
        files = self._document_files(target)
        documents: list[KnowledgeDocument] = []
        for file_path in files:
            extracted = extract_document(file_path)
            chunks = chunk_text(extracted.text)
            if not chunks:
                raise ValueError(f"{file_path} does not contain extractable text")
            documents.append(
                self.store.upsert_knowledge_document(
                    path=str(extracted.path),
                    title=extracted.title,
                    kind=extracted.kind,
                    checksum=extracted.checksum,
                    modified_at=extracted.modified_at,
                    chunks=chunks,
                )
            )
        return documents

    def _validate_allowed_path(self, target: Path) -> None:
        try:
            target.relative_to(self.allowed_root)
        except ValueError as exc:
            message = f"{target} is outside allowed document root {self.allowed_root}"
            raise ValueError(message) from exc

    @staticmethod
    def _document_files(target: Path) -> list[Path]:
        if target.is_file():
            if target.suffix.lower() not in SUPPORTED_SUFFIXES:
                raise ValueError(f"{target} is not a supported document type")
            return [target]
        if not target.is_dir():
            raise ValueError(f"{target} does not exist")
        return sorted(
            path
            for path in target.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
        )


def extract_document(path: Path) -> ExtractedDocument:
    suffix = path.suffix.lower()
    raw_bytes = path.read_bytes()
    if suffix == ".pdf":
        text = extract_pdf_text(path)
        title = path.stem.replace("-", " ").replace("_", " ").strip().title()
    else:
        text = path.read_text(encoding="utf-8").strip()
        title = extract_title(text, path)
    if not text.strip():
        raise ValueError(f"{path} does not contain extractable text")
    return ExtractedDocument(
        path=path,
        title=title,
        kind=suffix.removeprefix("."),
        text=text,
        checksum=hashlib.sha256(raw_bytes).hexdigest(),
        modified_at=datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
    )


def extract_pdf_text(path: Path) -> str:
    try:
        reader = PdfReader(str(path))
        page_text = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise ValueError(f"{path} could not be read as a text PDF") from exc
    text = "\n\n".join(part.strip() for part in page_text if part.strip()).strip()
    if not text:
        raise ValueError(f"{path} does not contain extractable text")
    return text


def extract_title(text: str, path: Path) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or path.stem
        return stripped[:80]
    return path.stem.replace("-", " ").replace("_", " ").strip().title()


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
