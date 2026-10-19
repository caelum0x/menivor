import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

vi.mock("@/lib/use-api-token", () => ({ useApiToken: () => async () => "token" }));

import AdminFunnelPage from "./page";
import { dayOrNo } from "./funnel-data";

const payload = {
  since: "2026-09-25T00:00:00+00:00",
  totals: {
    users: 2,
    reach: { signed_up: 2, card_check: 1, first_render: 1, first_kept: 1, first_payment: 0 },
    by_source: { scribase: 1, unknown: 1 },
    by_plan: { free: 2 },
  },
  rows: [
    {
      user_id: "u1", email: "a@example.com", signed_up: "2026-09-26T10:00:00+00:00",
      card_check: "2026-09-26T10:05:00+00:00", first_render: "2026-09-26T11:00:00+00:00",
      first_kept: "2026-09-26T11:00:00+00:00", first_payment: null, plan: "free", source: "scribase",
      utm_source: "unknown", utm_medium: "unknown", utm_campaign: "launch-video", referrer: "unknown",
    },
  ],
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("admin funnel page", () => {
  it("renders reach, mixes and rows, with 'no' and 'unknown' for missing data", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        calls.push(url);
        const body = { status: 200, data: payload };
        return { ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) };
      }),
    );
    render(<AdminFunnelPage />);
    const row = await screen.findByText("a@example.com");
    expect(calls[0]).toMatch(/\/admin\/funnel\/readout\?since=2026-09-25$/);
    const cells = within(row.closest("tr") as HTMLElement).getAllByRole("cell").map((c) => c.textContent);
    expect(cells).toContain("no");
    expect(cells).toContain("scribase");
    expect(screen.getAllByText("unknown").length).toBeGreaterThan(0);
    expect(dayOrNo(null)).toBe("no");
  });

  it("shows the API's refusal for a non-admin", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        const body = { status: 403, message: "staff access required" };
        return { ok: false, status: 403, json: async () => body, text: async () => JSON.stringify(body) };
      }),
    );
    render(<AdminFunnelPage />);
    expect(await screen.findByRole("alert")).toBeTruthy();
  });
});
