from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from pypdf import PdfWriter
from reportlab.pdfgen import canvas

from wait_local_agent.knowledge import KnowledgeIngestionService
from wait_local_agent.providers import provider_from_settings
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
