import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { EndUserSupport } from "../src/screens/EndUserSupport";

describe("EndUserSupport", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.stubGlobal("fetch", vi.fn());
  });

  it("submits, looks up, and escalates a scoped request with the end-user token", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(json({ brand_name: "Acme Support", brand_tagline: "Help for Acme teams" }))
      .mockResolvedValueOnce(json({ ticket_id: "EUS-1", subject: "Cannot sign in", status: "new", priority: "normal" }))
      .mockResolvedValueOnce(json({ ticket_id: "EUS-1", subject: "Cannot sign in", status: "new", priority: "normal" }))
      .mockResolvedValueOnce(json([]))
      .mockResolvedValueOnce(json({ id: 1, ticket_id: "EUS-1", body: "More details", created_at: "2026-08-09T00:00:00Z" }))
      .mockResolvedValueOnce(json({ ticket_id: "EUS-1", subject: "Cannot sign in", status: "escalated", priority: "normal" }));

    render(<MemoryRouter><EndUserSupport /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Support access token"), { target: { value: "scoped-token" } });
    fireEvent.click(screen.getByRole("button", { name: "Save access" }));
    expect(await screen.findByText("Acme Support")).toBeInTheDocument();
    expect(screen.getByText("Help for Acme teams")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Subject"), { target: { value: "Cannot sign in" } });
    fireEvent.change(screen.getByLabelText("Details"), { target: { value: "MFA is blocked" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit request" }));

    expect(await screen.findByText("Your request EUS-1 was submitted.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Check status" }));
    expect(await screen.findByText("Status: new")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Send a follow-up"), { target: { value: "More details" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect(await screen.findByText("Your message was sent to the support team.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ask for technician attention" }));
    expect(await screen.findByText("Your request was marked for technician attention.")).toBeInTheDocument();

    const brandingCall = fetchMock.mock.calls[0];
    const firstCall = fetchMock.mock.calls[1];
    const escalationCall = fetchMock.mock.calls[5];
    expect(brandingCall?.[0]).toBe("/end-user/config");
    expect(new Headers(brandingCall?.[1]?.headers).get("Authorization")).toBe("Bearer scoped-token");
    expect(firstCall?.[0]).toBe("/end-user/tickets");
    expect(new Headers(firstCall?.[1]?.headers).get("Authorization")).toBe("Bearer scoped-token");
    expect(escalationCall?.[0]).toBe("/end-user/tickets/EUS-1/escalate");
    expect(new Headers(escalationCall?.[1]?.headers).get("Authorization")).toBe("Bearer scoped-token");
  });

  it("handles missing access, empty results, and denied requests without fake success", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ detail: "end-user access required" }), { status: 403 })));

    render(<EndUserSupport />);
    fireEvent.change(screen.getByLabelText("Request number"), { target: { value: "EUS-404" } });
    expect(screen.getByRole("button", { name: "Check status" })).toBeDisabled();
    expect(fetchMock).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Support access token"), { target: { value: "wrong-token" } });
    fireEvent.click(screen.getByRole("button", { name: "Save access" }));
    fireEvent.click(screen.getByRole("button", { name: "Check status" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(await screen.findByRole("alert")).toHaveTextContent("You do not have permission to do that.");
    expect(screen.getByText("Your request details will appear here after a successful lookup.")).toBeInTheDocument();
  });

  it("offers an operator return link without sending the operator token to the portal", async () => {
    window.localStorage.setItem("wait-local-agent-api-token", "operator-token");
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue(json({ brand_name: "WAIT Support", brand_tagline: "Private help desk" }));

    render(<EndUserSupport />);

    expect(screen.getByRole("link", { name: "Back to WAIT dashboard" })).toHaveAttribute("href", "/");
    fireEvent.change(screen.getByLabelText("Support access token"), { target: { value: "scoped-token" } });
    fireEvent.click(screen.getByRole("button", { name: "Save access" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/end-user/config",
      expect.objectContaining({ headers: expect.any(Headers) })
    ));
    const request = fetchMock.mock.calls[0]?.[1];
    expect(new Headers(request?.headers).get("Authorization")).toBe("Bearer scoped-token");
  });
});

function json(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    headers: { "Content-Type": "application/json" },
    status: 200
  });
}
