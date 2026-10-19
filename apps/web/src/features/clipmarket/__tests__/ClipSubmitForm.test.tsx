import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ClipSubmitForm } from "../ClipSubmitForm";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: async () => "test-token" }),
}));

function envelope(data: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "OK",
    headers: { get: () => null },
    text: async () => JSON.stringify({ status, data }),
  } as unknown as Response;
}

describe("ClipSubmitForm (clipmarket extension)", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("POSTs the clip URL to the campaign submit endpoint and renders the result", async () => {
    fetchMock.mockResolvedValueOnce(
      envelope({
        id: "sub1",
        campaign_id: "camp_42",
        clipper_id: "u1",
        clip_url: "https://x/clip",
        verified_views: 1200,
        payable_micros: 2_400_000,
        status: "pending",
        fraud_score: 0,
        fraud_flags: "",
      }),
    );

    render(<ClipSubmitForm campaignId="camp_42" />);

    fireEvent.change(screen.getByLabelText("Clip URL"), {
      target: { value: "https://x/clip" },
    });
    fireEvent.click(screen.getByRole("button", { name: /submit/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain("/clipmarket/campaigns/camp_42/submit");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ clip_url: "https://x/clip" });
    expect(init.headers["Idempotency-Key"]).toBeTruthy();

    expect(await screen.findByText(/1,200 views/)).toBeInTheDocument();
    expect(screen.getByText("pending")).toBeInTheDocument();
  });

  it("keeps the submit button disabled until a URL is entered", () => {
    render(<ClipSubmitForm campaignId="camp_42" />);
    expect(screen.getByRole("button", { name: /submit/i })).toBeDisabled();
  });
});
