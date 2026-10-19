import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { CreateTabs } from "./CreateTabs";
import { AiVideoCreate } from "./AiVideoCreate";

// Signed-in account whose free reels are unlocked (card check done).
const getToken = async () => "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1MSJ9.sig";
const auth = { getToken, isLoaded: true, isSignedIn: true };
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
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
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

const CAPABILITIES = {
  status: 200,
  data: {
    mode: "standard",
    generation: { reels: true, broll: true },
    product: { runtime: { storage_ready: true } },
  },
};

const DEVICE_SESSION = {
  status: 200,
  data: {
    api_key: "rf_device_test",
    created: false,
    credits: 3,
    user_id: "u1",
  },
};

const ME = { status: 200, data: { credits: 3 } };
const EMPTY_GENERATIONS = { status: 200, data: [] };

/**
 * Route fetches by path. `onGenerate` decides the POST /generation/broll/generate
 * response so each test can exercise a different failure mode.
 */
function stubFetch(onGenerate?: () => Response, launchStatus?: unknown) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push(`${init?.method ?? "GET"} ${url}`);
      if (url.includes("/launch/status")) {
        return jsonResponse({ status: 200, data: launchStatus ?? { mode: "public" } });
      }
      if (url.includes("/auth/device")) return jsonResponse(DEVICE_SESSION);
      if (url.includes("/billing/card-check")) {
        return jsonResponse({
          status: 200,
          data: {
            unlocked: true,
            available: true,
            credits: 3,
            price_usd: 1,
            card_check_credits: 1,
            free_credits: 3,
          },
        });
      }
      if (url.includes("/pilot/capabilities")) return jsonResponse(CAPABILITIES);
      if (url.includes("/me")) return jsonResponse(ME);
      if (url.includes("/generation/broll/generate")) {
        return onGenerate
          ? onGenerate()
          : jsonResponse({
              status: 200,
              data: {
                generation_id: "gen1",
                state: 4,
                progress: 0,
                broll_key: "",
                result_url: "",
                duration: 5,
                error: "",
                retry_eligible: false,
              },
            });
      }
      if (url.includes("/generation/broll/generations"))
        return jsonResponse(EMPTY_GENERATIONS);
      return jsonResponse({ status: 200, data: {} });
    }),
  );
  return calls;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("CreateTabs", () => {
  it("defaults to the free narration tab and switches to AI video", async () => {
    stubFetch();
    render(<CreateTabs />);

    // Free path is the default landing tab.
    expect(
      screen.getByRole("tab", { name: /narration reel/i }),
    ).toHaveAttribute("aria-selected", "true");

    fireEvent.click(screen.getByRole("tab", { name: /ai video/i }));
    await waitFor(() =>
      expect(screen.getByText(/describe your video/i)).toBeInTheDocument(),
    );
    // Honest pricing copy is visible before any submit (tab hint + cost line).
    expect(screen.getAllByText(/uses 3|3 credits/i).length).toBeGreaterThan(0);
  });
});

describe("AiVideoCreate", () => {
  async function fillAndSubmit() {
    await waitFor(() =>
      expect(screen.getByText(/describe your video/i)).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByPlaceholderText(/origami boat/i), {
      target: { value: "a red fox running through snow" },
    });
    fireEvent.click(screen.getByRole("button", { name: /generate ai video/i }));
  }

  it("submits a t2v generation to /generation/broll/generate", async () => {
    const calls = stubFetch();
    render(<AiVideoCreate />);
    await fillAndSubmit();
    await waitFor(() =>
      expect(
        calls.some((c) => c.startsWith("POST") && c.includes("/generation/broll/generate")),
      ).toBe(true),
    );
    // The new render appears in the session list.
    await waitFor(() =>
      expect(screen.getByText(/generating/i)).toBeInTheDocument(),
    );
  });

  it("shows the at-capacity state on a 429", async () => {
    stubFetch(() =>
      jsonResponse(
        { status: 429, message: "AI video generation is at capacity today" },
        { ok: false, status: 429 },
      ),
    );
    render(<AiVideoCreate />);
    await fillAndSubmit();
    await waitFor(() =>
      expect(screen.getByText(/at capacity today/i)).toBeInTheDocument(),
    );
  });

  it("shows the insufficient-credits state on a 402", async () => {
    stubFetch(() =>
      jsonResponse(
        { status: 402, message: "insufficient credits" },
        { ok: false, status: 402 },
      ),
    );
    render(<AiVideoCreate />);
    await fillAndSubmit();
    await waitFor(() =>
      expect(screen.getByText(/out of credits/i)).toBeInTheDocument(),
    );
    expect(screen.getByRole("link", { name: /view plans/i })).toBeInTheDocument();
  });

  it("names the locked format on a 402 format_locked instead of blaming credits", async () => {
    stubFetch(() =>
      jsonResponse(
        {
          status: 402,
          message: "req: This format is not available yet (AI B-roll generation is not configured)",
          data: {
            code: "format_locked",
            format: "ai_broll",
            reason: "AI B-roll generation is not configured",
          },
        },
        { ok: false, status: 402 },
      ),
    );
    render(<AiVideoCreate />);
    await fillAndSubmit();
    await waitFor(() =>
      expect(
        screen.getByText(/AI video is not available on this server yet: AI B-roll generation is not configured/i),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText(/out of credits/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /view plans/i })).not.toBeInTheDocument();
  });

  it("disables submit with the reason when /launch/status locks AI video", async () => {
    const calls = stubFetch(undefined, {
      mode: "public",
      available_formats: [{ id: "captions_only_byov", label: "Captions over your own video" }],
      locked_formats: [
        {
          id: "ai_broll",
          label: "AI B-roll clips",
          code: "format_locked",
          reason: "no AI B-roll provider is configured",
        },
      ],
    });
    render(<AiVideoCreate />);
    await waitFor(() =>
      expect(screen.getByText(/no AI B-roll provider is configured/i)).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByPlaceholderText(/origami boat/i), {
      target: { value: "a red fox running through snow" },
    });
    const submit = screen.getByRole("button", { name: /generate ai video/i });
    expect(submit).toBeDisabled();
    fireEvent.click(submit);
    expect(calls.some((c) => c.includes("/generation/broll/generate"))).toBe(false);
  });
});
