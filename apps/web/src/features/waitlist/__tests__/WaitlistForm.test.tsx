import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { WaitlistForm } from "@/components/marketing/WaitlistForm";
import { WAITLIST_FALLBACK_EMAIL } from "@/lib/waitlist";

const fetchMock = vi.fn();

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function submitEmail(email: string): void {
  fireEvent.change(screen.getByLabelText(/email address/i), {
    target: { value: email },
  });
  fireEvent.submit(
    screen.getByRole("button", { name: /join the waitlist/i }).closest("form")!,
  );
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("WaitlistForm", () => {
  it("posts the email with its source tag and shows the success state", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { ok: true }));
    render(<WaitlistForm source="hero" />);

    submitEmail("creator@example.com");

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(/on the list/i),
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/waitlist");
    expect(JSON.parse(String(init.body))).toEqual({
      email: "creator@example.com",
      source: "hero",
      company: "",
    });
  });

  it("shows the server validation message on a 400", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(400, { ok: false, error: "Please enter a valid email address." }),
    );
    render(<WaitlistForm source="hero" />);

    submitEmail("broken@example.com");

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/valid email/i),
    );
  });

  it("falls back to a mailto link when the endpoint is unavailable (503)", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(503, { ok: false, fallbackEmail: WAITLIST_FALLBACK_EMAIL }),
    );
    render(<WaitlistForm source="landing-cta" />);

    submitEmail("creator@example.com");

    await waitFor(() => {
      const link = screen.getByRole("link", { name: WAITLIST_FALLBACK_EMAIL });
      expect(link).toHaveAttribute(
        "href",
        expect.stringContaining(`mailto:${WAITLIST_FALLBACK_EMAIL}`),
      );
    });
  });

  it("falls back to the mailto link on a network failure", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    render(<WaitlistForm source="hero" />);

    submitEmail("creator@example.com");

    await waitFor(() =>
      expect(
        screen.getByRole("link", { name: WAITLIST_FALLBACK_EMAIL }),
      ).toBeInTheDocument(),
    );
  });
});
