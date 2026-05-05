from __future__ import annotations

from pathlib import Path

from wait_local_agent.models import SourceReference, Ticket


def retrieve_sources(ticket: Ticket, doc_root: Path) -> list[SourceReference]:
    if not doc_root.exists():
        return []

    keywords = f"{ticket.subject} {ticket.body}".lower()
    scored_sources: list[tuple[int, SourceReference]] = []
    for path in sorted(doc_root.glob("*.md")):
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            continue
        title = content.splitlines()[0].removeprefix("# ").strip()
        tokens = path.stem.replace("-", " ").split()
        score = sum(1 for token in tokens if token in keywords)
        scored_sources.append(
            (
                score,
                SourceReference(
                    title=title,
                    path=str(path),
                    excerpt=" ".join(content.split()[0:28]),
                ),
            )
        )

    positive_matches = [item for item in scored_sources if item[0] > 0]
    ranked = positive_matches or scored_sources
    ranked.sort(key=lambda item: (-item[0], item[1].title))
    return [source for _, source in ranked[:3]]
