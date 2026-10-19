import { describe, expect, it } from "vitest";

import { isDefinitiveTransferFailureStatus } from "./transfer-outcome";

describe("mobile transfer outcome classification", () => {
  it("clears only explicit pre-command non-mutating failures", () => {
    for (const status of [400, 401, 402, 403, 404, 409, 410, 422]) {
      expect(isDefinitiveTransferFailureStatus(status)).toBe(true);
    }
  });

  it("retains the pending key for throttling and other ambiguous outcomes", () => {
    for (const status of [0, 408, 425, 429, 500, 502, 503]) {
      expect(isDefinitiveTransferFailureStatus(status)).toBe(false);
    }
  });
});
