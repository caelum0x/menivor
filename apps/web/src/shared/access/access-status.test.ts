import { describe, expect, it } from "vitest";
import { accessStatusFor, runSizeFor, type CardCheckStatus } from "./api";

const base: CardCheckStatus = {
  unlocked: false,
  available: true,
  credits: 0,
  price_usd: 1,
  card_check_credits: 1,
  free_credits: 3,
};

describe("accessStatusFor", () => {
  it("locks a new account that has not passed the card check", () => {
    expect(accessStatusFor(base)).toBe("locked");
  });

  it("lets an account with its free first reel create before the card check", () => {
    expect(accessStatusFor({ ...base, credits: 1, first_reel_ready: true })).toBe("ready");
  });

  it("is ready once unlocked, or while payments are paused", () => {
    expect(accessStatusFor({ ...base, unlocked: true })).toBe("ready");
    expect(accessStatusFor({ ...base, paused: true })).toBe("ready");
  });
});

describe("runSizeFor", () => {
  it("makes three hook variants for unlocked accounts", () => {
    expect(runSizeFor({ ...base, unlocked: true, credits: 4 }, 3)).toBe(3);
  });

  it("makes one reel on the free first reel", () => {
    expect(runSizeFor({ ...base, credits: 1, first_reel_ready: true }, 3)).toBe(1);
  });

  it("defaults to the full run when the status is unknown", () => {
    expect(runSizeFor(null, 3)).toBe(3);
  });
});
