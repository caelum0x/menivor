import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

import { ChannelConsole } from "../ChannelConsole";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: async () => "test-token" }),
}));

const launchMock = vi.hoisted(() => ({
  state: {
    status: "ready",
    gate: {
      phase: "public",
      staffOverride: false,
      publishing: { open: true, reason: "" } as { open: boolean; reason: string },
      checkout: { open: true, reason: "" },
    },
  },
}));
vi.mock("@/src/shared/launch-gate/use-launch-gate", () => ({ useLaunchGate: () => launchMock.state }));


function envelope(data: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "OK",
    headers: { get: () => null },
    // Hoist `message` to the envelope top level so ApiError picks it up on errors.
    text: async () =>
      JSON.stringify({ status, data, message: (data as { message?: string })?.message }),
  } as unknown as Response;
}

/** Route mocked fetch by request path. */
function routeFetch(map: Record<string, () => Response>) {
  return vi.fn(async (url: string) => {
    for (const [needle, make] of Object.entries(map)) {
      if (url.includes(needle)) return make();
    }
    throw new Error(`unexpected fetch: ${url}`);
  });
}

describe("ChannelConsole", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("loads and renders connected channels + scheduled queue", async () => {
    const impl = routeFetch({
      "/me/connections": () =>
        envelope([
          {
            provider: "tiktok",
            external_account_id: "acme",
            connected: true,
            status: "connected",
            scopes: "",
          },
        ]),
      "/me/scheduled": () =>
        envelope([
          {
            id: "s1",
            job_id: "job_9",
            platforms: ["tiktok"],
            scheduled_at: "2026-01-01T00:00:00Z",
            status: "pending",
          },
        ]),
    });
    fetchMock.mockImplementation(impl);

    render(<ChannelConsole />);

    expect(await screen.findByText("@acme")).toBeInTheDocument();
    expect(screen.getAllByText("tiktok").length).toBeGreaterThan(0);
    await waitFor(() =>
      expect(screen.getByText(/job job_9/)).toBeInTheDocument(),
    );
    // Both read models were fetched.
    const urls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(urls.some((u) => u.includes("/me/connections"))).toBe(true);
    expect(urls.some((u) => u.includes("/me/scheduled"))).toBe(true);
  });

  it("renders the empty state when there are no channels", async () => {
    fetchMock.mockImplementation(
      routeFetch({
        "/me/connections": () => envelope([]),
        "/me/scheduled": () => envelope([]),
      }),
    );

    render(<ChannelConsole />);

    expect(await screen.findByText(/No channels connected yet/)).toBeInTheDocument();
    expect(await screen.findByText(/Nothing scheduled yet/)).toBeInTheDocument();
  });

  it("surfaces an error when the channels request fails", async () => {
    fetchMock.mockImplementation(
      routeFetch({
        "/me/connections": () => envelope({ message: "channels down" }, 503),
        "/me/scheduled": () => envelope([]),
      }),
    );

    render(<ChannelConsole />);

    // Server failures surface as short, readable copy (never the raw message).
    expect(await screen.findByText(/went wrong on our side/)).toBeInTheDocument();
  });
});
