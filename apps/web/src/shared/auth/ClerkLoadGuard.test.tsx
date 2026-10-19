import { afterEach, describe, expect, it } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ClerkLoadGuard } from "./ClerkLoadGuard";

afterEach(() => {
  cleanup();
});

function rejectWith(message: string) {
  // jsdom has no PromiseRejectionEvent constructor; build a plain Event and
  // attach `reason`, which is all ClerkLoadGuard's listener reads. Wrapped in
  // act() because dispatching directly on `window` bypasses React's
  // fireEvent batching.
  act(() => {
    const event = new Event("unhandledrejection") as Event & { reason: unknown };
    event.reason = new Error(message);
    window.dispatchEvent(event);
  });
}

describe("ClerkLoadGuard", () => {
  it("renders nothing until Clerk fails to load", () => {
    render(<ClerkLoadGuard />);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows an actionable banner when clerk-js fails to load", () => {
    render(<ClerkLoadGuard />);
    rejectWith('Clerk: Failed to load Clerk, failed to load script: ... (code="failed_to_load_clerk_js")');
    expect(screen.getByRole("alert")).toHaveTextContent(/sign-in couldn.t load/i);
    expect(screen.getByRole("button", { name: /reload page/i })).toBeInTheDocument();
  });

  it("ignores unrelated rejections", () => {
    render(<ClerkLoadGuard />);
    rejectWith("Network request failed");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("dismisses the banner on click", () => {
    render(<ClerkLoadGuard />);
    rejectWith('failed_to_load_clerk_js');
    fireEvent.click(screen.getByRole("button", { name: /dismiss/i }));
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
