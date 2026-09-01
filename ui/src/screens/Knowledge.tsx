import { FormEvent, useCallback, useEffect, useState } from "react";
import { useDashboard } from "../app/DashboardContext";
import { apiFetch } from "../api/client";
import { type KnowledgeChunk, type KnowledgeDocument } from "../api/types";
import { ClientIdSelect } from "../components/ClientIdSelect";
import { RoleGate } from "../components/RoleGate";

export type KnowledgeParser = "auto" | "plain" | "markdown" | "pdf";
const KNOWLEDGE_AUTHORITY_OPTIONS = [
  "AUTHORITATIVE_POLICY",
  "APPROVED_SOP",
  "REFERENCE",
  "VENDOR",
  "TECHNICIAN_NOTES",
  "UNTRUSTED",
] as const;

export function parserPayload(parser: KnowledgeParser): "" | "basic" | "pypdf" {
  if (parser === "auto") return "";
  if (parser === "pdf") return "pypdf";
  return "basic";
}

export function Knowledge() {
  const { clients = [], isAdmin, canWrite, role, roleResolved, selectedClientId, setSelectedClientId } = useDashboard();
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [chunks, setChunks] = useState<KnowledgeChunk[]>([]);
  const [path, setPath] = useState("");
  const [parser, setParser] = useState<KnowledgeParser>("auto");
  const [ocr, setOcr] = useState(true);
  const [searchText, setSearchText] = useState("");
  const [searchLimit, setSearchLimit] = useState(3);
  const [searchBackend, setSearchBackend] = useState("");
  const [searchClientId, setSearchClientId] = useState("");
  const [statusMessage, setStatusMessage] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [authorityDocumentId, setAuthorityDocumentId] = useState<number | null>(null);
  const [authorityDraft, setAuthorityDraft] = useState("");
  const [sopVersionDraft, setSopVersionDraft] = useState("");

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
    if (!selectedClientId) {
      setStatusMessage("Select a client from the top bar before ingesting documents.");
      return;
    }
    setIsLoading(true);
    setStatusMessage("Ingesting documents...");
    try {
      const result = await apiFetch<KnowledgeDocument[]>("/knowledge/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, parser: parserPayload(parser), ocr, client_id: selectedClientId })
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
      const params = new URLSearchParams({ q: searchText, limit: String(searchLimit) });
      if (searchBackend) params.set("backend", searchBackend);
      if (searchClientId.trim()) params.set("client_id", searchClientId.trim());
      const found = await apiFetch<KnowledgeChunk[]>(`/knowledge/search?${params.toString()}`);
      setChunks(found);
      setStatusMessage(`${found.length} results found.`);
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Knowledge search failed.");
    } finally {
      setIsLoading(false);
    }
  }

  function beginAuthorityEdit(document: KnowledgeDocument) {
    setAuthorityDocumentId(document.id);
    setAuthorityDraft(document.authority);
    setSopVersionDraft(document.sop_version ?? "");
  }

  async function saveAuthority(documentId: number) {
    setIsLoading(true);
    setStatusMessage("Saving document authority...");
    try {
      const updated = await apiFetch<KnowledgeDocument>(`/knowledge/documents/${documentId}/authority`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          authority: authorityDraft,
          sop_version: sopVersionDraft || null,
        }),
      });
      setDocuments((current) => current.map((document) => document.id === updated.id ? updated : document));
      setAuthorityDocumentId(null);
      setStatusMessage("Document authority updated.");
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Document authority could not be updated.");
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
              <select value={parser} onChange={(event) => setParser(event.target.value as KnowledgeParser)}>
                <option value="auto">auto</option>
                <option value="plain">plain text</option>
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
            <ClientIdSelect label="Client ID" value={selectedClientId} onChange={setSelectedClientId} clients={clients} required id="knowledge-ingest-client-id" />
          </div>
          {!selectedClientId ? <p className="screen-note">Select a client from the top bar before running ingest.</p> : null}
          <button type="submit" disabled={isLoading || !path || !canWrite || !selectedClientId} title={!selectedClientId ? "Select a client from the top bar first" : undefined}>
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
              <div>
                <strong>Authority: {document.authority}</strong>
                <span>{document.sop_version ? `SOP version: ${document.sop_version}` : "No SOP version"}</span>
                {document.approved_by ? <span>Approved by: {document.approved_by}</span> : null}
                <em>{document.indexed_at}</em>
              </div>
              <RoleGate role={role} resolved={roleResolved} allowed={["admin"]}>
                {authorityDocumentId === document.id ? (
                  <div>
                    <label>
                      Authority
                      <select value={authorityDraft} onChange={(event) => setAuthorityDraft(event.target.value)} disabled={isLoading}>
                        {KNOWLEDGE_AUTHORITY_OPTIONS.map((authority) => <option key={authority} value={authority}>{authority}</option>)}
                      </select>
                    </label>
                    <label>
                      SOP version
                      <input value={sopVersionDraft} maxLength={200} onChange={(event) => setSopVersionDraft(event.target.value)} disabled={isLoading} />
                    </label>
                    <button type="button" onClick={() => void saveAuthority(document.id)} disabled={isLoading}>{isLoading ? "Saving..." : "Save authority"}</button>
                    <button className="secondary-button" type="button" onClick={() => setAuthorityDocumentId(null)} disabled={isLoading}>Cancel</button>
                  </div>
                ) : (
                  <button className="secondary-button" type="button" onClick={() => beginAuthorityEdit(document)} disabled={isLoading}>Change authority</button>
                )}
              </RoleGate>
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
            aria-label="Search result limit"
            value={searchLimit}
            min={1}
            max={20}
            onChange={(event) => setSearchLimit(Number(event.target.value))}
          />
          <button className="icon-button" type="submit">Search</button>
        </form>
        <details className="technical-details">
          <summary>Advanced search controls</summary>
          <div className="grid">
            <label>
              Search backend
              <input value={searchBackend} onChange={(event) => setSearchBackend(event.target.value)} placeholder="sqlite, fts, or qdrant" />
            </label>
            <ClientIdSelect label="Client ID" value={searchClientId} onChange={setSearchClientId} clients={clients} id="knowledge-search-client-id" />
          </div>
        </details>
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
