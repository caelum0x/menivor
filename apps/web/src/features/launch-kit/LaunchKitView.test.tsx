import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

const auth = { isLoaded: true, isSignedIn: true };

vi.mock("@/components/auth/clerk-safe", () => ({ useAuth: () => auth }));
vi.mock("@/lib/auth-redirect", () => ({ signInHref: (path: string) => `/sign-in?redirect=${path}` }));
vi.mock("@/src/shared/device/session", () => ({ getStoredDeviceApiKey: () => "" }));
// The four sections make their own API calls; this view's own test only
// covers the sign-in gate, so render them as simple stand-ins.
vi.mock("./PlatformChecklist", () => ({ PlatformChecklist: () => <div data-testid="section-platforms" /> }));
vi.mock("./PainPointFinder", () => ({ PainPointFinder: () => <div data-testid="section-pain-points" /> }));
vi.mock("./CompetitorBacklinks", () => ({ CompetitorBacklinks: () => <div data-testid="section-backlinks" /> }));
vi.mock("./LaunchChecklist", () => ({ LaunchChecklist: () => <div data-testid="section-checklist" /> }));

import { LaunchKitView } from "./LaunchKitView";

describe("LaunchKitView", () => {
  beforeEach(() => {
    auth.isSignedIn = true;
  });

  it("signed-in users see all four sections and a product field", async () => {
    render(<LaunchKitView />);
    expect(await screen.findByTestId("section-platforms")).toBeTruthy();
    expect(screen.getByTestId("section-pain-points")).toBeTruthy();
    expect(screen.getByTestId("section-backlinks")).toBeTruthy();
    expect(screen.getByTestId("section-checklist")).toBeTruthy();
    expect(screen.getByLabelText("Product")).toBeTruthy();
  });

  it("signed-out visitors are sent to sign in, never an error", async () => {
    auth.isSignedIn = false;
    render(<LaunchKitView />);
    expect(await screen.findByText("Sign in for your launch kit")).toBeTruthy();
    expect(screen.queryByTestId("section-platforms")).toBeNull();
  });
});
