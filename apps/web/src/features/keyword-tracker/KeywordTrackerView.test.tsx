import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { KeywordTrackerOverview, TrackedKeyword } from "./api";

const auth = { isLoaded: true, isSignedIn: true };
const listKeywords = vi.fn();
const addKeyword = vi.fn();
const removeKeyword = vi.fn();
const refreshKeyword = vi.fn();
const listAppStoreApps = vi.fn();

// A stable function reference (the real hook memoizes via useCallback); an
// inline `() => async () => "tok"` would hand back a new function identity
// every render, which would re-trigger KeywordTrackerView's load effect
// (it depends on `load`, which depends on `getApiToken`) on every commit.
const getApiToken = async () => "tok";

const myWorkspaces = vi.fn(() => ({ workspaces: [] as readonly { id: string; name: string }[] }));

vi.mock("@/components/auth/clerk-safe", () => ({ useAuth: () => auth }));
vi.mock("@/lib/use-api-token", () => ({ useApiToken: () => getApiToken }));
vi.mock("@/lib/use-my-workspaces", () => ({ useMyWorkspaces: () => myWorkspaces() }));
vi.mock("@/lib/auth-redirect", () => ({ signInHref: (path: string) => `/sign-in?redirect=${path}` }));
vi.mock("@/src/shared/device/session", () => ({ getStoredDeviceApiKey: () => "" }));
vi.mock("@/app/settings/integrations/_lib/api", () => ({ listAppStoreApps: (...a: unknown[]) => listAppStoreApps(...a) }));
vi.mock("./api", async (orig) => {
  const actual = await orig<typeof import("./api")>();
  return {
    ...actual,
    listKeywords: (...a: unknown[]) => listKeywords(...a),
    addKeyword: (...a: unknown[]) => addKeyword(...a),
    removeKeyword: (...a: unknown[]) => removeKeyword(...a),
    refreshKeyword: (...a: unknown[]) => refreshKeyword(...a),
  };
});

import { KeywordTrackerView } from "./KeywordTrackerView";

const keyword = (over: Partial<TrackedKeyword>): TrackedKeyword => ({
  id: "k1", app_id: "999", app_name: "CalDesk", country: "us", term: "fitness tracker", current_rank: 4,
  checked_count: 50, last_checked_at: "2026-10-15T05:00:00Z", last_error: "", change_7d: 2, change_30d: null,
  history: [{ date: "2026-10-14", position: 6 }, { date: "2026-10-15", position: 4 }], popularity: null,
  ...over,
});

const overview = (keywords: readonly TrackedKeyword[], extra: Partial<KeywordTrackerOverview> = {}): KeywordTrackerOverview => ({
  keywords, limit: 10, paid: false, apple_ads_connected: false, ...extra,
});

describe("KeywordTrackerView", () => {
  beforeEach(() => {
    listKeywords.mockReset();
    addKeyword.mockReset();
    removeKeyword.mockReset();
    refreshKeyword.mockReset();
    listAppStoreApps.mockReset().mockResolvedValue({ apps: [] });
    myWorkspaces.mockReset().mockReturnValue({ workspaces: [] });
    auth.isSignedIn = true;
  });

  it("empty state invites adding the first keyword", async () => {
    listKeywords.mockResolvedValue(overview([]));
    render(<KeywordTrackerView />);
    expect(await screen.findByText("See where you rank")).toBeTruthy();
    expect(screen.getByTestId("keyword-limit").textContent).toBe("0 / 10 keywords tracked");
  });

  it("shows a tracked keyword's rank, change and never a fake position for an unranked one", async () => {
    listKeywords.mockResolvedValue(
      overview([keyword({}), keyword({ id: "k2", term: "macro tracker", current_rank: null, change_7d: null, history: [] })]),
    );
    render(<KeywordTrackerView />);
    expect(await screen.findByText("fitness tracker")).toBeTruthy();
    expect(screen.getByText("#4")).toBeTruthy();
    expect(screen.getByText("+2")).toBeTruthy();
    expect(screen.getByText("Not in top 50")).toBeTruthy();
  });

  it("adding a keyword calls the API and appends the row", async () => {
    listKeywords.mockResolvedValue(overview([]));
    addKeyword.mockResolvedValue(keyword({}));
    render(<KeywordTrackerView />);
    await screen.findByText("See where you rank");

    fireEvent.change(screen.getByLabelText("App Store numeric id"), { target: { value: "999" } });
    fireEvent.change(screen.getByLabelText("Keyword to track"), { target: { value: "fitness tracker" } });
    fireEvent.click(screen.getByRole("button", { name: "Track" }));

    expect(await screen.findByText("fitness tracker")).toBeTruthy();
    expect(addKeyword).toHaveBeenCalledWith(
      { appId: "999", term: "fitness tracker", appName: "", country: "us" },
      { token: "tok" },
    );
  });

  it("removing a keyword calls the API and drops the row", async () => {
    listKeywords.mockResolvedValue(overview([keyword({})]));
    removeKeyword.mockResolvedValue({ removed: true });
    render(<KeywordTrackerView />);
    await screen.findByText("fitness tracker");

    fireEvent.click(screen.getByLabelText("Stop tracking this keyword"));
    await screen.findByText("See where you rank"); // empty state once the row is gone
    expect(removeKeyword).toHaveBeenCalledWith("k1", { token: "tok" });
  });

  it("at the free-tier limit, the form disables and an upgrade link appears", async () => {
    listKeywords.mockResolvedValue(overview([keyword({})], { limit: 1 }));
    render(<KeywordTrackerView />);
    await screen.findByText("fitness tracker");
    const limitText = screen.getByTestId("keyword-limit").textContent ?? "";
    expect(limitText).toContain("1 / 1 keywords tracked");
    expect(screen.getByRole("link", { name: "Upgrade to track more" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Track" })).toBeDisabled();
  });

  it("signed out users are sent to sign in, not an error", async () => {
    auth.isSignedIn = false;
    render(<KeywordTrackerView />);
    expect(await screen.findByText("Sign in to track keywords")).toBeTruthy();
    expect(listKeywords).not.toHaveBeenCalled();
  });

  it("with no Apple Ads connection, popularity is hidden and the page points at Settings", async () => {
    listKeywords.mockResolvedValue(overview([keyword({ popularity: null })]));
    render(<KeywordTrackerView />);
    await screen.findByText("fitness tracker");
    expect(screen.queryByText(/Popularity \d+\/100/)).toBeNull();
    expect(screen.getByRole("link", { name: "connect one in Settings" })).toBeTruthy();
    expect(listKeywords).toHaveBeenCalledWith(undefined, { token: "tok" });
  });

  it("with a connected Apple Ads account, each keyword shows its real popularity score", async () => {
    myWorkspaces.mockReturnValue({ workspaces: [{ id: "ws_1", name: "Acme" }] });
    listKeywords.mockResolvedValue(overview([keyword({ popularity: 72 })], { apple_ads_connected: true }));
    render(<KeywordTrackerView />);
    await screen.findByText("fitness tracker");
    expect(screen.getByText("· Popularity 72/100")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "connect one in Settings" })).toBeNull();
    expect(listKeywords).toHaveBeenCalledWith("ws_1", { token: "tok" });
  });
});
