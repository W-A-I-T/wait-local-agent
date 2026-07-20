import { FormEvent, useCallback, useEffect, useState } from "react";
import { useDashboard } from "../app/DashboardContext";
import { apiFetch } from "../api/client";
import { type KnowledgeChunk, type KnowledgeDocument } from "../api/types";

export function Knowledge() {
  const { isAdmin, canWrite } = useDashboard();
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [chunks, setChunks] = useState<KnowledgeChunk[]>([]);
  const [path, setPath] = useState("");
  const [parser, setParser] = useState("auto");
  const [ocr, setOcr] = useState(true);
  const [searchText, setSearchText] = useState("");
  const [searchLimit, setSearchLimit] = useState(3);
  const [statusMessage, setStatusMessage] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const loadDocuments = useCallback(async () => {
    try {
      const loaded = await apiFetch<KnowledgeDocument[]>('/knowledge/documents');
      setDocuments(loaded);
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Failed to load knowledge documents.");
    }
  }, []);

  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  async function handleIngest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!path) {
      setStatusMessage("Set a path before ingesting documents.");
      return;
    }
    setIsLoading(true);
    setStatusMessage("Ingesting documents...");
    try {
      const result = await apiFetch<KnowledgeDocument[]>("/knowledge/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, parser: parser || null, ocr })
      });
      setDocuments((current) => [
        ...result,
        ...current.filter((item) => !result.some((ingested) => ingested.path === item.path))
      ]);
      setStatusMessage(`Ingest complete: ${result.length} document(s) processed.`);
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Knowledge ingest failed.");
    } finally {
      setIsLoading(false);
    }
  }

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!searchText) {
      setChunks([]);
      setStatusMessage("Enter a query to search.");
      return;
    }
    setIsLoading(true);
    try {
      const found = await apiFetch<KnowledgeChunk[]>(
        `/knowledge/search?q=${encodeURIComponent(searchText)}&limit=${searchLimit}`
      );
      setChunks(found);
      setStatusMessage(`${found.length} results found.`);
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Knowledge search failed.");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className="screen-stack">
      <section className="panel knowledge-panel">
        <div className="panel-heading">
          <h2>Knowledge</h2>
          <span>{documents.length} documents indexed</span>
        </div>
        <form className="draft-form" onSubmit={handleIngest}>
          <div className="grid">
            <label>
              Local path
              <input value={path} onChange={(event) => setPath(event.target.value)} placeholder="/path/to/docs" />
            </label>
            <label>
              Parser
              <select value={parser} onChange={(event) => setParser(event.target.value)}>
                <option value="auto">auto</option>
                <option value="plain">plain</option>
                <option value="markdown">markdown</option>
                <option value="pdf">pdf</option>
              </select>
            </label>
            <label className="switch-label">
              <input
                type="checkbox"
                checked={ocr}
                onChange={(event) => setOcr(event.target.checked)}
              />
              OCR documents
            </label>
          </div>
          <button type="submit" disabled={isLoading || !path || !canWrite}>
            {isLoading ? "Ingesting..." : "Run ingest"}
          </button>
        </form>

        {statusMessage ? <div className="notice">{statusMessage}</div> : null}

        <div className="document-list">
          {documents.length === 0 ? <p>No documents indexed yet.</p> : null}
          {documents.map((document) => (
            <article className="document-row" key={document.id}>
              <div>
                <strong>{document.title || document.path}</strong>
                <span>{document.kind} · {document.chunk_count} chunks</span>
                <em>{document.path}</em>
              </div>
              <em>{document.indexed_at}</em>
            </article>
          ))}
        </div>
      </section>

      <section className="panel settings-panel">
        <div className="panel-heading">
          <h2>Knowledge Search</h2>
          <span>{chunks.length} result(s)</span>
        </div>
        <form className="search-box" onSubmit={handleSearch}>
          <input
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
            placeholder="Search indexed documents"
          />
          <input
            type="number"
            value={searchLimit}
            min={1}
            max={20}
            onChange={(event) => setSearchLimit(Number(event.target.value))}
          />
          <button className="icon-button" type="submit">Search</button>
        </form>
        <div className="source-results">
          {chunks.map((chunk) => (
            <article key={chunk.id}>
              <strong>{chunk.title || chunk.path}</strong>
              <span>{chunk.excerpt || chunk.text.slice(0, 160)}</span>
              <p>{chunk.path}</p>
            </article>
          ))}
          {chunks.length === 0 ? <p>No results yet.</p> : null}
        </div>
      </section>

      {!isAdmin ? <p className="screen-note">Admin users can configure indexing and run large ingests.</p> : null}
    </div>
  );
}
