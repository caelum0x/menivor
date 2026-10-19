import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

const auth = { isLoaded: true, isSignedIn: false, getToken: async () => null };
const getMe = vi.fn();
const listJobsPage = vi.fn();
let deviceKey = "";

vi.mock("@/components/auth/clerk-safe", () => ({ useAuth: () => auth }));
vi.mock("@/components/app-shell/AppTopBar", () => ({ AppTopBar: () => null }));
vi.mock("@/components/app-shell/CreditsLink", () => ({ CreditsLink: () => null }));
vi.mock("@/src/features/onboarding/GuestClaimCard", () => ({ GuestClaimCard: () => null }));
vi.mock("@/src/shared/device/session", async (orig) => {
  const actual = await orig<typeof import("@/src/shared/device/session")>();
  return { ...actual, getStoredDeviceApiKey: () => deviceKey };
});
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    getMe: (...args: unknown[]) => getMe(...args),
    listJobsPage: (...args: unknown[]) => listJobsPage(...args),
  };
});

import { ReelsLibraryPage } from "./ReelsLibraryPage";

describe("ReelsLibraryPage signed out", () => {
  beforeEach(() => {
    getMe.mockReset();
    listJobsPage.mockReset();
    deviceKey = "";
  });

  it("shows the sign-in prompt without calling the API", async () => {
    render(<ReelsLibraryPage />);
    expect(await screen.findByText("Sign in to see your reels.")).toBeTruthy();
    expect(getMe).not.toHaveBeenCalled();
    expect(listJobsPage).not.toHaveBeenCalled();
  });

  it("still loads a guest session saved in this browser", async () => {
    deviceKey = "mvr_device_key";
    getMe.mockResolvedValue({ user_id: "g", email: "device+x@menivor.com", credits: 0, jobs_count: 0 });
    listJobsPage.mockResolvedValue({ jobs: [], hasMore: false, nextOffset: 0 });
    render(<ReelsLibraryPage />);
    await vi.waitFor(() => expect(listJobsPage).toHaveBeenCalled());
    expect(getMe).toHaveBeenCalled();
  });
});
