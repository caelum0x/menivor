import * as React from "react";
import { render, renderHook, cleanup, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * W3-A smoke test: with NO real Clerk key the root layout never mounts
 * <ClerkProvider>. Every raw Clerk hook/component would then throw, so this
 * mocks `@clerk/nextjs` to throw on use and proves the signed-in app pages
 * still render through `components/auth/clerk-safe`.
 */
vi.mock("@/lib/clerk", () => ({
  hasRealClerkKey: false,
  clerkPublishableKey: "",
  WAITLIST_MODE: false,
}));

vi.mock("@clerk/nextjs", () => {
  const boom = () => {
    throw new Error("raw Clerk used without <ClerkProvider>");
  };
  return {
    useAuth: boom,
    useClerk: boom,
    useUser: boom,
    SignIn: boom,
    SignUp: boom,
    SignedIn: boom,
    SignedOut: boom,
    UserButton: boom,
  };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
  redirect: vi.fn(),
  notFound: vi.fn(),
}));

beforeEach(() => {
  // Requests stay pending: this test is about mounting, not data.
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function mount(node: React.ReactElement) {
  const errors = vi.spyOn(console, "error").mockImplementation(() => {});
  await act(async () => {
    render(node);
  });
  const thrown = errors.mock.calls.filter((c) =>
    String(c[0]).includes("raw Clerk used"),
  );
  errors.mockRestore();
  expect(thrown).toEqual([]);
}

describe("app pages without a Clerk key", () => {
  it("renders /publish", async () => {
    const { default: PublishPage } = await import("./publish/page");
    await mount(await PublishPage({ searchParams: Promise.resolve({}) }));
  });

  it("renders /studio", async () => {
    const { default: StudioPage } = await import("./studio/page");
    await mount(<StudioPage />);
  });

  it("renders /studio/dub", async () => {
    const { default: StudioDubPage } = await import("./studio/dub/page");
    await mount(<StudioDubPage />);
  });

  it("renders /calendar", async () => {
    const { default: CalendarPage } = await import("./calendar/page");
    await mount(<CalendarPage />);
  });

  it("renders /inbox", async () => {
    const { default: InboxLayout } = await import("./inbox/layout");
    const { default: InboxPage } = await import("./inbox/page");
    await mount(
      <InboxLayout>
        <InboxPage />
      </InboxLayout>,
    );
  });
});

describe("clerk-safe fallbacks", () => {
  it("useAuth returns a stable signed-out state with a null token", async () => {
    const { useAuth } = await import("@/components/auth/clerk-safe");
    const { result, rerender } = renderHook(() => useAuth());
    const first = result.current;
    rerender();
    expect(result.current.getToken).toBe(first.getToken);
    expect(result.current.isLoaded).toBe(true);
    expect(result.current.isSignedIn).toBe(false);
    await expect(result.current.getToken()).resolves.toBeNull();
  });

  it("useClerk().signOut resolves without a session", async () => {
    const { useClerk } = await import("@/components/auth/clerk-safe");
    const { result } = renderHook(() => useClerk());
    await expect(result.current.signOut()).resolves.toBeUndefined();
  });

  it("SignIn shows an honest not-configured notice", async () => {
    const { SignIn } = await import("@/components/auth/clerk-safe");
    const { getByText } = render(<SignIn />);
    expect(getByText("Accounts are not enabled here")).toBeInTheDocument();
  });
});
