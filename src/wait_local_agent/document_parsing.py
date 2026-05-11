from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from pypdf import PdfReader

SUPPORTED_BASIC_SUFFIXES = {".md", ".txt", ".pdf"}
SUPPORTED_DOCLING_SUFFIXES = {
    ".md",
    ".txt",
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".html",
    ".htm",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
}


@dataclass(frozen=True)
class ExtractedDocument:
    path: Path
    title: str
    kind: str
    text: str
    checksum: str
    modified_at: str


class DocumentParser(Protocol):
    supported_suffixes: set[str]

    def extract(self, path: Path) -> ExtractedDocument:
        """Extract plain text from a local document."""


class BasicDocumentParser:
    supported_suffixes = SUPPORTED_BASIC_SUFFIXES

    def extract(self, path: Path) -> ExtractedDocument:
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
        return _extracted(path, title, suffix, text, raw_bytes)


class DoclingDocumentParser:
    supported_suffixes = SUPPORTED_DOCLING_SUFFIXES

    def __init__(self, *, allow_ocr: bool = False) -> None:
        self.allow_ocr = allow_ocr

    def extract(self, path: Path) -> ExtractedDocument:
        raw_bytes = path.read_bytes()
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as exc:
            raise ValueError(
                "Docling parser requires the optional docling extra; "
                'install with pip install -e ".[docling]".'
            ) from exc

        try:
            result = _docling_converter(DocumentConverter, self.allow_ocr).convert(path)
            text = result.document.export_to_markdown().strip()
        except Exception as exc:
            mode = "with OCR enabled" if self.allow_ocr else "with OCR disabled"
            raise ValueError(f"{path} could not be parsed by Docling {mode}") from exc

        if not text:
            message = f"{path} does not contain extractable text"
            if not self.allow_ocr:
                message += "; enable WAIT_ALLOW_OCR=true to try OCR-capable parsing"
            raise ValueError(message)
        return _extracted(path, extract_title(text, path), path.suffix.lower(), text, raw_bytes)


def parser_for_name(name: str, *, allow_ocr: bool = False) -> DocumentParser:
    normalized = name.strip().lower()
    if normalized in {"", "basic", "pypdf"}:
        return BasicDocumentParser()
    if normalized == "docling":
        return DoclingDocumentParser(allow_ocr=allow_ocr)
    raise ValueError(f"unsupported document parser: {name}")


def _docling_converter(document_converter_type: type, allow_ocr: bool):
    if not allow_ocr:
        return document_converter_type()
    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import PdfFormatOption
    except ImportError as exc:
        raise ValueError(
            "Docling OCR requires Docling PDF pipeline options; "
            'install with pip install -e ".[docling]".'
        ) from exc

    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = True
    return document_converter_type(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
        }
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


def _extracted(
    path: Path, title: str, suffix: str, text: str, raw_bytes: bytes
) -> ExtractedDocument:
    return ExtractedDocument(
        path=path,
        title=title,
        kind=suffix.removeprefix("."),
        text=text,
        checksum=hashlib.sha256(raw_bytes).hexdigest(),
        modified_at=datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
    )
