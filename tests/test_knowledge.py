from __future__ import annotations

import sys
import types
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from pypdf import PdfWriter
from reportlab.pdfgen import canvas

from wait_local_agent.knowledge import (
    KnowledgeIngestionService,
    chunk_text,
    extract_document,
    extract_title,
    ingestion_service_from_settings,
)
from wait_local_agent.models import KnowledgeChunk, Ticket
from wait_local_agent.providers import provider_from_settings
from wait_local_agent.retrieval import retrieve_sources
from wait_local_agent.services import TicketIntelligenceService
from wait_local_agent.store import MAX_SEARCH_LIMIT, Store, _bounded_search_limit
from wait_local_agent.vector_search import search_backend_from_settings


def write_text_pdf(path: Path, text: str) -> None:
    pdf = canvas.Canvas(str(path))
    pdf.drawString(72, 720, text)
    pdf.save()


def write_blank_pdf(path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with path.open("wb") as output:
        writer.write(output)


def test_ingests_markdown_text_and_pdf(settings, tmp_path) -> None:
    doc_root = tmp_path / "docs"
    doc_root.mkdir()
    (doc_root / "mfa-reset.md").write_text(
        "# MFA Reset\n\nReset MFA after proofing.", encoding="utf-8"
    )
    (doc_root / "printer.txt").write_text(
        "Printer Triage\n\nClear queue and test driver.", encoding="utf-8"
    )
    write_text_pdf(doc_root / "license-request.pdf", "License request approval and assignment")
    active_settings = replace(settings, allowed_doc_root=doc_root)
    store = Store(active_settings.data_path)
    service = KnowledgeIngestionService(store, active_settings.allowed_doc_root)

    documents = service.ingest_path(doc_root)

    assert len(documents) == 3
    assert {document.kind for document in documents} == {"md", "txt", "pdf"}
    assert store.knowledge_chunk_count() == 3


def test_rejects_paths_outside_allowed_root(settings, tmp_path) -> None:
    doc_root = tmp_path / "docs"
    outside = tmp_path / "outside"
    doc_root.mkdir()
    outside.mkdir()
    target = outside / "secret.txt"
    target.write_text("outside", encoding="utf-8")
    active_settings = replace(settings, allowed_doc_root=doc_root)
    service = KnowledgeIngestionService(
        Store(active_settings.data_path), active_settings.allowed_doc_root
    )

    with pytest.raises(ValueError, match="outside allowed document root"):
        service.ingest_path(target)


def test_directory_ingest_rejects_symlink_escape(settings, tmp_path) -> None:
    doc_root = tmp_path / "docs"
    outside = tmp_path / "outside"
    doc_root.mkdir()
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("outside secret", encoding="utf-8")
    (doc_root / "valid.md").write_text("# Valid\n\nAllowed content.", encoding="utf-8")
    (doc_root / "leak.txt").symlink_to(secret)
    active_settings = replace(settings, allowed_doc_root=doc_root)
    store = Store(active_settings.data_path)
    service = KnowledgeIngestionService(store, active_settings.allowed_doc_root)

    with pytest.raises(ValueError, match="outside allowed document root"):
        service.ingest_path(doc_root)

    assert store.list_knowledge_documents() == []


def test_reingest_replaces_chunks_without_duplicates(settings, tmp_path) -> None:
    doc_root = tmp_path / "docs"
    doc_root.mkdir()
    runbook = doc_root / "mailbox.txt"
    runbook.write_text("Mailbox Runbook\n\nFirst version.", encoding="utf-8")
    active_settings = replace(settings, allowed_doc_root=doc_root)
    store = Store(active_settings.data_path)
    service = KnowledgeIngestionService(store, active_settings.allowed_doc_root)

    service.ingest_path(runbook)
    runbook.write_text("Mailbox Runbook\n\nUpdated mailbox permissions.", encoding="utf-8")
    service.ingest_path(runbook)

    documents = store.list_knowledge_documents()
    assert len(documents) == 1
    assert documents[0].chunk_count == 1
    assert store.knowledge_chunk_count() == 1
    assert (
        "Updated mailbox permissions"
        in store.search_knowledge_chunks("mailbox permissions")[0].text
    )


def test_search_returns_ranked_chunks(settings, tmp_path) -> None:
    doc_root = tmp_path / "docs"
    doc_root.mkdir()
    (doc_root / "mfa.md").write_text(
        "# MFA Reset\n\nReset MFA and revoke stale sessions.", encoding="utf-8"
    )
    (doc_root / "printer.md").write_text("# Printer Triage\n\nRestart spooler.", encoding="utf-8")
    active_settings = replace(settings, allowed_doc_root=doc_root)
    store = Store(active_settings.data_path)
    KnowledgeIngestionService(store, active_settings.allowed_doc_root).ingest_path(doc_root)

    results = store.search_knowledge_chunks("MFA sessions")

    assert results[0].title == "MFA Reset"


def test_ticket_summary_uses_indexed_sources(settings, tmp_path) -> None:
    doc_root = tmp_path / "docs"
    doc_root.mkdir()
    (doc_root / "mfa-reset.md").write_text(
        "# MFA Reset\n\nReset MFA after proofing.", encoding="utf-8"
    )
    (doc_root / "shared-mailbox.md").write_text(
        "# Shared Mailbox Runbook\n\nApprove mailbox members before permissions.",
        encoding="utf-8",
    )
    active_settings = replace(settings, allowed_doc_root=doc_root)
    store = Store(active_settings.data_path)
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    KnowledgeIngestionService(store, active_settings.allowed_doc_root).ingest_path(doc_root)
    service = TicketIntelligenceService(
        store, active_settings, provider_from_settings(active_settings)
    )

    summary = service.summarize("TCK-1002")

    assert summary.sources[0].title == "Shared Mailbox Runbook"
    assert summary.sources[0].chunk_id is not None


def test_empty_pdf_fails_without_indexing(settings, tmp_path) -> None:
    doc_root = tmp_path / "docs"
    doc_root.mkdir()
    pdf_path = doc_root / "blank.pdf"
    write_blank_pdf(pdf_path)
    active_settings = replace(settings, allowed_doc_root=doc_root)
    store = Store(active_settings.data_path)
    service = KnowledgeIngestionService(store, active_settings.allowed_doc_root)

    with pytest.raises(ValueError, match="extractable text"):
        service.ingest_path(pdf_path)

    assert store.list_knowledge_documents() == []


def test_directory_ingest_failure_leaves_no_partial_index(settings, tmp_path) -> None:
    doc_root = tmp_path / "docs"
    doc_root.mkdir()
    (doc_root / "valid.md").write_text("# Valid\n\nThis should not persist.", encoding="utf-8")
    write_blank_pdf(doc_root / "blank.pdf")
    active_settings = replace(settings, allowed_doc_root=doc_root)
    store = Store(active_settings.data_path)
    service = KnowledgeIngestionService(store, active_settings.allowed_doc_root)

    with pytest.raises(ValueError, match="extractable text"):
        service.ingest_path(doc_root)

    assert store.list_knowledge_documents() == []
    assert store.knowledge_chunk_count() == 0


def test_unsupported_document_extension_errors(settings, tmp_path) -> None:
    doc_root = tmp_path / "docs"
    doc_root.mkdir()
    unsupported = doc_root / "runbook.docx"
    unsupported.write_text("not supported", encoding="utf-8")
    active_settings = replace(settings, allowed_doc_root=doc_root)
    service = KnowledgeIngestionService(Store(active_settings.data_path), doc_root)

    with pytest.raises(ValueError, match="not a supported document type"):
        service.ingest_path(unsupported)


class FakeInputFormat:
    PDF = "pdf"
    IMAGE = "image"


class FakePdfPipelineOptions:
    def __init__(self, *, do_ocr: bool = True) -> None:
        self.do_ocr = do_ocr


class FakeFormatOption:
    def __init__(self, *, pipeline_options: FakePdfPipelineOptions) -> None:
        self.pipeline_options = pipeline_options


def install_fake_docling(monkeypatch: pytest.MonkeyPatch, document_converter: type[Any]) -> None:
    docling_module = types.ModuleType("docling")
    datamodel_module = types.ModuleType("docling.datamodel")
    base_models_module = types.ModuleType("docling.datamodel.base_models")
    pipeline_options_module = types.ModuleType("docling.datamodel.pipeline_options")
    converter_module = types.ModuleType("docling.document_converter")
    cast(Any, base_models_module).InputFormat = FakeInputFormat
    cast(Any, pipeline_options_module).PdfPipelineOptions = FakePdfPipelineOptions
    cast(Any, converter_module).DocumentConverter = document_converter
    cast(Any, converter_module).ImageFormatOption = FakeFormatOption
    cast(Any, converter_module).PdfFormatOption = FakeFormatOption
    monkeypatch.setitem(sys.modules, "docling", docling_module)
    monkeypatch.setitem(sys.modules, "docling.datamodel", datamodel_module)
    monkeypatch.setitem(sys.modules, "docling.datamodel.base_models", base_models_module)
    monkeypatch.setitem(sys.modules, "docling.datamodel.pipeline_options", pipeline_options_module)
    monkeypatch.setitem(sys.modules, "docling.document_converter", converter_module)


def test_docling_parser_missing_dependency_errors_cleanly(settings, tmp_path) -> None:
    doc_root = tmp_path / "docs"
    doc_root.mkdir()
    pdf_path = doc_root / "runbook.pdf"
    write_text_pdf(pdf_path, "Text that Docling would parse")
    active_settings = replace(settings, allowed_doc_root=doc_root, document_parser="docling")
    service = ingestion_service_from_settings(Store(active_settings.data_path), active_settings)

    with pytest.raises(ValueError, match="Docling parser requires"):
        service.ingest_path(pdf_path)


def test_docling_parser_uses_lazy_document_converter(settings, tmp_path, monkeypatch) -> None:
    doc_root = tmp_path / "docs"
    doc_root.mkdir()
    pdf_path = doc_root / "runbook.pdf"
    pdf_path.write_bytes(b"%PDF fake enough for mocked docling")

    class FakeDocument:
        def export_to_markdown(self) -> str:
            return "# Mocked Docling\n\nOCR content"

    class FakeResult:
        document = FakeDocument()

    class FakeDocumentConverter:
        def __init__(self, *, format_options: dict[Any, Any] | None = None) -> None:
            assert format_options is not None
            assert format_options[FakeInputFormat.PDF].pipeline_options.do_ocr is True
            assert format_options[FakeInputFormat.IMAGE].pipeline_options.do_ocr is True

        def convert(self, path: Path) -> FakeResult:
            assert path == pdf_path
            return FakeResult()

    install_fake_docling(monkeypatch, FakeDocumentConverter)
    active_settings = replace(
        settings, allowed_doc_root=doc_root, document_parser="docling", allow_ocr=True
    )
    store = Store(active_settings.data_path)

    documents = ingestion_service_from_settings(store, active_settings).ingest_path(pdf_path)

    assert documents[0].title == "Mocked Docling"
    assert store.search_knowledge_chunks("OCR content")[0].title == "Mocked Docling"


def test_docling_parser_wires_ocr_pipeline_options(settings, tmp_path, monkeypatch) -> None:
    doc_root = tmp_path / "docs"
    doc_root.mkdir()
    pdf_path = doc_root / "scan.pdf"
    pdf_path.write_bytes(b"%PDF fake enough for mocked docling")
    captured: dict[str, object] = {}

    class FakeDocument:
        def export_to_markdown(self) -> str:
            return "# OCR\n\nScanned content"

    class FakeResult:
        document = FakeDocument()

    class FakeDocumentConverter:
        def __init__(self, *, format_options: dict[Any, Any] | None = None) -> None:
            assert format_options is not None
            captured["format_options"] = format_options

        def convert(self, path: Path) -> FakeResult:
            assert path == pdf_path
            return FakeResult()

    install_fake_docling(monkeypatch, FakeDocumentConverter)
    active_settings = replace(
        settings,
        allowed_doc_root=doc_root,
        document_parser="docling",
        allow_ocr=True,
    )

    documents = ingestion_service_from_settings(
        Store(active_settings.data_path),
        active_settings,
    ).ingest_path(pdf_path)
    format_options = cast(dict[str, Any], captured["format_options"])

    assert documents[0].title == "OCR"
    assert format_options[FakeInputFormat.PDF].pipeline_options.do_ocr is True
    assert format_options[FakeInputFormat.IMAGE].pipeline_options.do_ocr is True


def test_docling_parser_empty_and_converter_error(settings, tmp_path, monkeypatch) -> None:
    doc_root = tmp_path / "docs"
    doc_root.mkdir()
    pdf_path = doc_root / "runbook.pdf"
    pdf_path.write_bytes(b"%PDF fake enough for mocked docling")

    class EmptyDocument:
        def export_to_markdown(self) -> str:
            return ""

    class EmptyResult:
        document = EmptyDocument()

    class EmptyDocumentConverter:
        def __init__(self, *, format_options: dict[Any, Any] | None = None) -> None:
            assert format_options is not None
            assert format_options[FakeInputFormat.PDF].pipeline_options.do_ocr is False
            assert format_options[FakeInputFormat.IMAGE].pipeline_options.do_ocr is False

        def convert(self, path: Path) -> EmptyResult:
            return EmptyResult()

    install_fake_docling(monkeypatch, EmptyDocumentConverter)
    active_settings = replace(settings, allowed_doc_root=doc_root, document_parser="docling")
    service = ingestion_service_from_settings(Store(active_settings.data_path), active_settings)

    with pytest.raises(ValueError, match="WAIT_ALLOW_OCR"):
        service.ingest_path(pdf_path)

    class BrokenDocumentConverter:
        def __init__(self, *, format_options: dict[Any, Any] | None = None) -> None:
            assert format_options is not None

        def convert(self, path: Path):
            raise RuntimeError("broken")

    install_fake_docling(monkeypatch, BrokenDocumentConverter)
    broken_service = ingestion_service_from_settings(
        Store(active_settings.data_path),
        active_settings,
    )
    with pytest.raises(ValueError, match="with OCR disabled"):
        broken_service.ingest_path(pdf_path)


def test_qdrant_remote_url_requires_http_probing(settings) -> None:
    active_settings = replace(
        settings,
        vector_backend="qdrant",
        qdrant_url="http://127.0.0.1:6333",
        allow_http_probing=False,
    )

    with pytest.raises(ValueError, match="WAIT_ALLOW_HTTP_PROBING"):
        search_backend_from_settings(active_settings, Store(active_settings.data_path))


def test_qdrant_local_backend_missing_dependency_errors(settings) -> None:
    active_settings = replace(settings, vector_backend="qdrant")

    with pytest.raises(ValueError, match="optional dependencies"):
        search_backend_from_settings(active_settings, Store(active_settings.data_path))


def test_unsupported_vector_backend_and_validation_helper(settings) -> None:
    from wait_local_agent.vector_search import validate_vector_settings

    with pytest.raises(ValueError, match="unsupported vector backend"):
        search_backend_from_settings(
            replace(settings, vector_backend="weird"),
            Store(settings.data_path),
        )
    with pytest.raises(ValueError, match="WAIT_ALLOW_HTTP_PROBING"):
        validate_vector_settings(
            replace(settings, vector_backend="qdrant", qdrant_url="http://qdrant.test")
        )
    validate_vector_settings(settings)


def test_qdrant_backend_upserts_and_searches_with_fake_modules(
    settings, tmp_path, monkeypatch
) -> None:
    points = []

    class FakeTextEmbedding:
        def __init__(self, model_name: str) -> None:
            assert model_name == settings.embedding_model

        def embed(self, texts):
            for text in texts:
                yield [float(len(text)), 1.0]

    class FakeQdrantClient:
        def __init__(self, **kwargs) -> None:
            assert "path" in kwargs
            self.created = False

        def collection_exists(self, collection_name: str) -> bool:
            assert collection_name == "wait_knowledge_chunks"
            return self.created

        def create_collection(self, collection_name: str, vectors_config) -> None:
            self.created = True

        def upsert(self, collection_name: str, points: list[object]) -> None:
            assert collection_name == "wait_knowledge_chunks"

        def search(self, collection_name: str, query_vector: list[float], limit: int):
            assert collection_name == "wait_knowledge_chunks"
            assert query_vector

            class Hit:
                payload = {
                    "chunk_id": 1,
                    "document_id": 2,
                    "title": "Vector Runbook",
                    "path": "docs/vector.md",
                    "chunk_index": 0,
                    "text": "vector text",
                    "excerpt": "vector",
                }

            return [Hit()]

    class FakeDistance:
        COSINE = "cosine"

    class FakeVectorParams:
        def __init__(self, size: int, distance: str) -> None:
            assert size == 2
            assert distance == "cosine"

    class FakePointStruct:
        def __init__(self, id: str, vector: list[float], payload: dict[str, object]) -> None:
            points.append((id, vector, payload))

    fastembed_module = types.ModuleType("fastembed")
    cast(Any, fastembed_module).TextEmbedding = FakeTextEmbedding
    qdrant_module = types.ModuleType("qdrant_client")
    cast(Any, qdrant_module).QdrantClient = FakeQdrantClient
    models_module = types.ModuleType("qdrant_client.models")
    cast(Any, models_module).Distance = FakeDistance
    cast(Any, models_module).VectorParams = FakeVectorParams
    cast(Any, models_module).PointStruct = FakePointStruct
    monkeypatch.setitem(sys.modules, "fastembed", fastembed_module)
    monkeypatch.setitem(sys.modules, "qdrant_client", qdrant_module)
    monkeypatch.setitem(sys.modules, "qdrant_client.models", models_module)
    active_settings = replace(settings, vector_backend="qdrant", qdrant_path=tmp_path / "qdrant")
    backend = search_backend_from_settings(active_settings, Store(active_settings.data_path))

    backend.upsert_document_chunks(
        [
            KnowledgeChunk(
                id=1,
                document_id=2,
                title="Vector Runbook",
                path="docs/vector.md",
                chunk_index=0,
                text="vector text",
                excerpt="vector",
            )
        ]
    )
    backend.upsert_document_chunks([])
    empty = backend.search("   ", limit=1)
    results = backend.search("vector", limit=1)

    assert points[0][2]["title"] == "Vector Runbook"
    assert empty == []
    assert results[0].title == "Vector Runbook"


def test_missing_ingest_path_errors(settings, tmp_path) -> None:
    doc_root = tmp_path / "docs"
    doc_root.mkdir()
    active_settings = replace(settings, allowed_doc_root=doc_root)
    service = KnowledgeIngestionService(Store(active_settings.data_path), doc_root)

    with pytest.raises(ValueError, match="does not exist"):
        service.ingest_path(doc_root / "missing.md")


def test_empty_text_file_fails_without_indexing(settings, tmp_path) -> None:
    doc_root = tmp_path / "docs"
    doc_root.mkdir()
    empty = doc_root / "empty.txt"
    empty.write_text("   ", encoding="utf-8")
    active_settings = replace(settings, allowed_doc_root=doc_root)
    store = Store(active_settings.data_path)
    service = KnowledgeIngestionService(store, doc_root)

    with pytest.raises(ValueError, match="extractable text"):
        service.ingest_path(empty)

    assert store.list_knowledge_documents() == []


def test_invalid_pdf_errors_clearly(tmp_path) -> None:
    bad_pdf = tmp_path / "bad.pdf"
    bad_pdf.write_text("not actually a pdf", encoding="utf-8")

    with pytest.raises(ValueError, match="could not be read as a text PDF"):
        extract_document(bad_pdf)


def test_empty_heading_uses_file_stem_title(tmp_path) -> None:
    assert extract_title("#", tmp_path / "fallback-title.md") == "fallback-title"


def test_title_skips_leading_blank_lines(tmp_path) -> None:
    assert extract_title("\n\nFirst real line", tmp_path / "fallback.md") == "First real line"


def test_blank_text_title_uses_pretty_file_stem(tmp_path) -> None:
    assert extract_title("", tmp_path / "printer_triage.md") == "Printer Triage"


def test_long_paragraph_chunking_is_deterministic() -> None:
    chunks = chunk_text("alpha " * 40, max_chars=50)

    assert len(chunks) > 1
    assert all(len(chunk) <= 50 for chunk in chunks)
    assert chunks == chunk_text("alpha " * 40, max_chars=50)


def test_chunk_text_splits_between_paragraphs() -> None:
    chunks = chunk_text("short\n\n" + "bravo " * 20, max_chars=80)

    assert chunks[0] == "short"
    assert len(chunks) > 1


def test_chunk_text_empty_input_returns_empty_list() -> None:
    assert chunk_text("") == []


def test_retrieval_falls_back_when_index_has_no_hits(settings, tmp_path) -> None:
    doc_root = tmp_path / "docs"
    doc_root.mkdir()
    (doc_root / "mfa-reset.md").write_text(
        "# MFA Reset\n\nReset MFA after proofing.", encoding="utf-8"
    )
    active_settings = replace(settings, allowed_doc_root=doc_root)
    store = Store(active_settings.data_path)
    KnowledgeIngestionService(store, active_settings.allowed_doc_root).ingest_path(doc_root)
    ticket = Ticket(
        id="TCK-2000",
        client="Acme",
        subject="unrelated satellite request",
        body="no matching indexed tokens",
        priority="low",
        status="new",
    )

    sources = retrieve_sources(ticket, active_settings.allowed_doc_root, store)

    assert sources
    assert sources[0].title == "MFA Reset"


def test_retrieval_returns_empty_when_doc_root_missing(settings, tmp_path) -> None:
    ticket = Ticket(
        id="TCK-2001",
        client="Acme",
        subject="mfa",
        body="reset",
        priority="low",
        status="new",
    )

    assert retrieve_sources(ticket, tmp_path / "missing", Store(settings.data_path)) == []


def test_retrieval_ignores_empty_markdown_files(settings, tmp_path) -> None:
    doc_root = tmp_path / "docs"
    doc_root.mkdir()
    (doc_root / "empty.md").write_text("", encoding="utf-8")
    ticket = Ticket(
        id="TCK-2002",
        client="Acme",
        subject="mfa",
        body="reset",
        priority="low",
        status="new",
    )

    assert retrieve_sources(ticket, doc_root, Store(settings.data_path)) == []


def test_store_knowledge_helpers_cover_empty_and_missing_paths(settings) -> None:
    store = Store(settings.data_path)

    assert store.upsert_knowledge_documents([]) == []
    assert store.get_knowledge_document(404) is None
    assert store.search_knowledge_chunks("") == []


def test_search_limit_is_clamped(settings) -> None:
    store = Store(settings.data_path)
    for index in range(3):
        store.upsert_knowledge_document(
            path=f"local-{index}.md",
            title=f"Local {index}",
            kind="md",
            checksum=f"abc-{index}",
            modified_at="2026-01-01T00:00:00+00:00",
            chunks=["shared local chunk"],
        )

    assert len(store.search_knowledge_chunks("shared", limit=-1)) == 1
    assert len(store.search_knowledge_chunks("shared", limit=100)) == 3


def test_bounded_search_limit_helper() -> None:
    assert _bounded_search_limit(-1) == 1
    assert _bounded_search_limit(0) == 1
    assert _bounded_search_limit(3) == 3
    assert _bounded_search_limit(999) == MAX_SEARCH_LIMIT


def test_single_document_upsert_path(settings) -> None:
    store = Store(settings.data_path)
    document = store.upsert_knowledge_document(
        path="local.md",
        title="Local",
        kind="md",
        checksum="abc",
        modified_at="2026-01-01T00:00:00+00:00",
        chunks=["local chunk"],
    )

    assert document.title == "Local"
    assert store.search_knowledge_chunks("local")[0].title == "Local"
