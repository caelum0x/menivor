import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

const refresh = vi.fn();
let paymentPhase: { phase: string; message?: string } = { phase: "none" };
vi.mock("@/src/shared/access", () => ({
  accessErrorMessage: () => "error",
  signUpHref: (next: string) => `/sign-up?next=${next}`,
  startCardCheck: vi.fn(),
  useCreemReturn: () => paymentPhase,
  useWebAccess: () => ({
    getToken: async () => "t",
    refresh,
    state: {
      status: "locked",
      card: { unlocked: false, available: true, credits: 0, price_usd: 1, card_check_credits: 1, free_credits: 3 },
    },
  }),
}));
vi.mock("@/lib/api", () => ({ ApiError: class extends Error {}, redeemReferral: vi.fn() }));

import { OnboardingFlow } from "./OnboardingFlow";

beforeEach(() => {
  vi.useFakeTimers();
  refresh.mockReset();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("OnboardingFlow card check", () => {
  it("offers the $1 unlock when nothing was paid yet", () => {
    paymentPhase = { phase: "none" };
    render(<OnboardingFlow next="/create" />);
    expect(screen.getByRole("button", { name: /Pay \$1 and unlock 4 reels/ })).toBeTruthy();
  });

  it("never offers a second payment while a paid checkout is confirming, and keeps re-checking", () => {
    paymentPhase = { phase: "pending", message: "Your payment is processing." };
    render(<OnboardingFlow next="/create" />);
    expect(screen.queryByRole("button", { name: /Pay \$1/ })).toBeNull();
    act(() => {
      vi.advanceTimersByTime(35_000);
    });
    expect(refresh).toHaveBeenCalledTimes(3);
    act(() => {
      vi.advanceTimersByTime(10 * 60_000);
    });
    expect(refresh).toHaveBeenCalledTimes(12);
    fireEvent.click(screen.getByRole("button", { name: /Check my payment now/ }));
    expect(refresh).toHaveBeenCalledTimes(13);
  });
});
