from __future__ import annotations

from pathlib import Path

from wait_local_agent.models import SourceReference, Ticket


def retrieve_sources(ticket: Ticket, doc_root: Path) -> list[SourceReference]:
    if not doc_root.exists():
        return []

    keywords = f"{ticket.subject} {ticket.body}".lower()
    candidates: list[SourceReference] = []
    for path in sorted(doc_root.glob("*.md")):
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            continue
        title = content.splitlines()[0].removeprefix("# ").strip()
        score = sum(1 for token in path.stem.replace("-", " ").split() if token in keywords)
        if score or not candidates:
            candidates.append(
                SourceReference(
                    title=title,
                    path=str(path),
                    excerpt=" ".join(content.split()[0:28]),
                )
            )
    return candidates[:3]

