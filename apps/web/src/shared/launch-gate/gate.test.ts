import { describe, expect, it } from "vitest";

import {
  cleanApiMessage,
  closedReason,
  gateFromStatus,
  readableApiError,
} from "./gate";

const RID = "0123456789abcdef0123456789abcdef";

function apiError(message: string, status: number, data?: unknown) {
  return Object.assign(new Error(message), {
    status,
    detail: { status, data, message },
  });
}

describe("gateFromStatus", () => {
  it("closes publishing and checkout in the private beta with honest reasons", () => {
    const gate = gateFromStatus({
      mode: "internal_pilot",
      public_access: false,
      phase: "private_beta",
      features: { signup: false, checkout: false, publishing: false },
    });
    expect(gate.phase).toBe("private_beta");
    expect(gate.publishing.open).toBe(false);
    expect(gate.publishing.reason).toMatch(/private beta/);
    expect(gate.checkout.open).toBe(false);
    expect(gate.checkout.reason).toMatch(/not be charged/);
    expect(gate.staffOverride).toBe(false);
  });

  it("opens both for pilot staff even in the private beta", () => {
    const gate = gateFromStatus({
      public_access: false,
      staff_override: true,
      features: { checkout: true, publishing: true },
    });
    expect(gate.staffOverride).toBe(true);
    expect(gate.publishing).toEqual({ open: true, reason: "" });
    expect(gate.checkout).toEqual({ open: true, reason: "" });
  });

  it("uses the switched-off copy when public but a feature flag is off", () => {
    const gate = gateFromStatus({ public_access: true, features: { publishing: false, checkout: true } });
    expect(gate.phase).toBe("public");
    expect(gate.publishing.reason).toBe(closedReason("publishing", "public"));
    expect(gate.checkout.open).toBe(true);
  });

  it("treats malformed documents as closed", () => {
    const gate = gateFromStatus("nope");
    expect(gate.publishing.open).toBe(false);
    expect(gate.checkout.open).toBe(false);
  });
});

describe("readableApiError", () => {
  it("maps a structured launch refusal to the server reason", () => {
    const err = apiError(`${RID}: direct publishing is not enabled for this launch phase`, 403, {
      code: "publishing_closed",
      reason: "Menivor is in private beta, so direct publishing is paused until public launch.",
    });
    expect(readableApiError(err, "x")).toBe(
      "Menivor is in private beta, so direct publishing is paused until public launch.",
    );
  });

  it("maps a legacy launch-phase message without a code", () => {
    const err = apiError(`${RID}: checkout is not enabled for this launch phase (correlation abc)`, 403);
    expect(readableApiError(err, "x")).toBe(closedReason("checkout", "private_beta"));
  });

  it("never shows a request id", () => {
    const err = apiError(`${RID}: this workspace already has a subscription; switch plans`, 409);
    const text = readableApiError(err, "x");
    expect(text).toBe("This workspace already has a subscription; switch plans");
    expect(text).not.toContain(RID);
  });

  it("gives short copy for transport, auth, rate-limit and server failures", () => {
    expect(readableApiError(apiError("Network error contacting the API: boom", 0), "x")).toMatch(/connection/);
    expect(readableApiError(apiError(`${RID}: invalid api key`, 401), "x")).toMatch(/Sign in again/);
    expect(readableApiError(apiError(`${RID}: slow down`, 429), "x")).toMatch(/Wait a minute/);
    const server = readableApiError(apiError(`${RID}: payment provider is unavailable`, 502), "x");
    expect(server).toMatch(/our side/);
    expect(server).not.toContain(RID);
  });

  it("falls back when there is nothing readable", () => {
    expect(readableApiError(null, "Failed to publish.")).toBe("Failed to publish.");
    expect(readableApiError(apiError(`${RID}: `, 400), "Failed.")).toBe("Failed.");
  });

  it("cleans plain messages", () => {
    expect(cleanApiMessage(`${RID}: post not found (correlation 9)`)).toBe("Post not found");
  });
});
