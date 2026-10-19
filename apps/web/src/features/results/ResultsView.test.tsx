import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { Results } from "./api";

const auth = { isLoaded: true, isSignedIn: true, getToken: async () => "tok" };
const getResults = vi.fn();
const syncResults = vi.fn();
const trackPostLink = vi.fn();

vi.mock("@/components/auth/clerk-safe", () => ({ useAuth: () => auth }));
vi.mock("@/lib/use-api-token", () => ({ useApiToken: () => async () => "tok" }));
vi.mock("@/src/shared/device/session", () => ({ getStoredDeviceApiKey: () => "" }));
vi.mock("./api", async (orig) => {
  const actual = await orig<typeof import("./api")>();
  return {
    ...actual,
    getResults: (...a: unknown[]) => getResults(...a),
    syncResults: (...a: unknown[]) => syncResults(...a),
    trackPostLink: (...a: unknown[]) => trackPostLink(...a),
  };
});

import { ResultsView } from "./ResultsView";
import { normalizeResults } from "./api";

const empty = normalizeResults({
  platforms: [
    { platform: "tiktok", label: "TikTok", connected: false, reads_numbers: false, needs_reconnect: false,
      reconnect_here: true, note: "" },
  ],
});

const withWinner: Results = normalizeResults({
  has_data: true,
  tracking: 2,
  totals: { posts: 2, views: 10000, engagements: 24 },
  winner: {
    hook: "Nobody tells you this.", posts: 1, views: 9000, avg_views: 9000, engagements: 12,
    engagement_rate: 0.0013, remake: { q: "https://shop.test/p", preset: "meme_hook" },
    why: "Averages 9,000 views per post, 9x your other hooks.",
  },
  posts: [
    { id: "p1", platform: "tiktok", label: "TikTok", url: "https://www.tiktok.com/video/1", title: "Nobody",
      from_menivor: true, state: "tracking", note: "", views: 9000, likes: 10, comments: 1, shares: 1,
      saves: null, last_checked_at: "2026-09-27T12:00:00Z", can_type_numbers: false },
    { id: "p2", platform: "youtube", label: "YouTube", url: "", title: "Other", from_menivor: false,
      state: "needs_access", note: "Connect YouTube so Menivor can read this post's numbers.", views: null,
      likes: null, comments: null, shares: null, saves: null, last_checked_at: null, can_type_numbers: true },
  ],
});

describe("ResultsView", () => {
  beforeEach(() => {
    getResults.mockReset();
    syncResults.mockReset();
    trackPostLink.mockReset();
    auth.isSignedIn = true;
  });

  it("empty state offers one action: connect TikTok", async () => {
    getResults.mockResolvedValue(empty);
    render(<ResultsView />);
    expect(await screen.findByRole("button", { name: "Connect TikTok" })).toBeTruthy();
    expect(screen.queryByLabelText("Post link")).toBeNull();
    fireEvent.click(screen.getByText("Or paste a post link"));
    expect(screen.getByLabelText("Post link")).toBeTruthy();
    expect(syncResults).not.toHaveBeenCalled();
  });

  it("without a TikTok app on the server, the paste field is the only action", async () => {
    getResults.mockResolvedValue(
      normalizeResults({
        platforms: [{ ...empty.platforms[0]!, can_connect: false }],
      }),
    );
    render(<ResultsView />);
    expect(await screen.findByLabelText("Post link")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Connect TikTok" })).toBeNull();
  });

  it("leads with the winning hook and a make-more link", async () => {
    getResults.mockResolvedValue(withWinner);
    syncResults.mockResolvedValue(withWinner);
    render(<ResultsView />);
    expect(await screen.findByText(/Nobody tells you this\./)).toBeTruthy();
    const make = screen.getByRole("link", { name: /Make more like this/ });
    expect(make.getAttribute("href")).toBe("/create?q=https%3A%2F%2Fshop.test%2Fp&preset=meme_hook&auto=1");
    // A post without numbers shows why, never a fake 0, and offers the hidden fallback.
    expect(screen.getByText(/Connect YouTube so Menivor/)).toBeTruthy();
    expect(screen.getByText("Enter numbers yourself")).toBeTruthy();
    expect(syncResults).toHaveBeenCalled();
  });

  it("signed out shows sign in without calling the API", async () => {
    auth.isSignedIn = false;
    render(<ResultsView />);
    expect(await screen.findByText("Sign in to see your results")).toBeTruthy();
    expect(getResults).not.toHaveBeenCalled();
  });
});
