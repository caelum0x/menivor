import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { BrollLibrary } from "./BrollLibrary";

const getToken = async () => "tok";
const auth = { getToken, isLoaded: true };
vi.mock("@clerk/nextjs", () => ({
  useAuth: () => auth,
  UserButton: () => null,
}));
vi.mock("next/link", () => ({
  __esModule: true,
  default: ({
    href,
    children,
  }: {
    href: string;
    children: React.ReactNode;
  }) => <a href={href}>{children}</a>,
}));

function jsonResponse(
  body: unknown,
  init: { ok?: boolean; status?: number } = {},
): Response {
  const ok = init.ok ?? true;
  return {
    ok,
    status: init.status ?? (ok ? 200 : 400),
    statusText: ok ? "OK" : "Error",
    text: async () => JSON.stringify(body),
    headers: { get: () => null },
  } as unknown as Response;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const CLIPS = {
  status: 200,
  data: [
    {
      generation_id: "gen_ready",
      state: 1,
      progress: 100,
      broll_key: "results/gen_ready.mp4",
      result_url: "https://cdn/gen_ready.mp4",
      duration: 5,
    },
    {
      generation_id: "gen_running",
      state: 4,
      progress: 40,
      broll_key: "",
      duration: 0,
    },
  ],
};

const PRESETS = {
  status: 200,
  data: [
    {
      id: "p1",
      name: "Slow zoom",
      description: "A gentle push-in",
      mode: "t2v",
      prompt_template: "",
      thumbnail_url: "",
      workflow_id: "",
      default_params: {},
    },
  ],
};

/** Route each fetch by URL so the parallel clip + preset loads are order-free. */
function routedFetch() {
  return vi.fn((url: string, _init?: { method?: string; body?: string }) => {
    if (url.includes("/generation/broll/presets"))
      return Promise.resolve(jsonResponse(PRESETS));
    if (url.includes("/generation/broll/generations"))
      return Promise.resolve(jsonResponse(CLIPS));
    return Promise.resolve(jsonResponse({ status: 200, data: [] }));
  });
}

describe("BrollLibrary", () => {
  it("loads clips from GET /generation/broll/generations and renders them", async () => {
    const fetchMock = routedFetch();
    vi.stubGlobal("fetch", fetchMock);

    render(<BrollLibrary />);

    await waitFor(() =>
      expect(screen.getByText("gen_ready")).toBeInTheDocument(),
    );

    const listCall = fetchMock.mock.calls.find((c) =>
      String(c[0]).includes("/generation/broll/generations?limit="),
    );
    expect(listCall).toBeTruthy();
    const listInit = listCall?.[1] as
      | { method?: string; headers: Record<string, string> }
      | undefined;
    expect(listInit?.method ?? "GET").toBe("GET");
    expect(listInit?.headers["x-api-key"]).toBe("tok");

    // Preset strip is wired to GET /generation/broll/presets.
    expect(
      fetchMock.mock.calls.some((c) =>
        String(c[0]).includes("/generation/broll/presets"),
      ),
    ).toBe(true);
    expect(screen.getByText("Slow zoom")).toBeInTheDocument();
  });

  it("filters to processing clips via the Processing chip", async () => {
    const fetchMock = routedFetch();
    vi.stubGlobal("fetch", fetchMock);

    render(<BrollLibrary />);
    await waitFor(() =>
      expect(screen.getByText("gen_ready")).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("tab", { name: /Processing/ }));

    await waitFor(() =>
      expect(screen.queryByText("gen_ready")).not.toBeInTheDocument(),
    );
    expect(screen.getByText("gen_running")).toBeInTheDocument();
  });

  it("offers a ready clip to the reel wizard", async () => {
    const fetchMock = routedFetch();
    vi.stubGlobal("fetch", fetchMock);

    render(<BrollLibrary />);
    await waitFor(() =>
      expect(screen.getByText("gen_ready")).toBeInTheDocument(),
    );

    expect(screen.getByRole("link", { name: /Use in a reel/ })).toHaveAttribute(
      "href",
      "/new",
    );
  });
});
