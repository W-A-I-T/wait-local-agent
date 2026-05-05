from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from pypdf import PdfWriter
from reportlab.pdfgen import canvas

from wait_local_agent.knowledge import (
    KnowledgeIngestionService,
    chunk_text,
    extract_document,
    extract_title,
)
from wait_local_agent.models import Ticket
from wait_local_agent.providers import provider_from_settings
from wait_local_agent.retrieval import retrieve_sources
from wait_local_agent.services import TicketIntelligenceService
from wait_local_agent.store import Store


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
