import { describe, expect, it } from "vitest";

import {
  ENTITLEMENT_MAX_AGE_MS,
  canExportWithEntitlement,
  entitlementSnapshotFromCustomerInfo,
  initialEntitlementSnapshot,
} from "../entitlement-policy";

const NOW = Date.UTC(2026, 7, 23, 12, 0, 0);
const USER_ID = "user_123";

function customerInfo({
  active = true,
  checkedAtMs = NOW,
  expiresAtMs = NOW + 86_400_000,
  verification = "VERIFIED",
}: {
  active?: boolean;
  checkedAtMs?: number;
  expiresAtMs?: number | null;
  verification?: string;
} = {}) {
  const entitlement = {
    isActive: active,
    expirationDateMillis: expiresAtMs,
    verification,
  };
  return {
    requestDate: new Date(checkedAtMs).toISOString(),
    entitlements: {
      all: { pro: entitlement },
      active: active ? { pro: entitlement } : {},
    },
  };
}

describe("RevenueCat export policy", () => {
  it("allows a fresh, active, verified Pro entitlement", () => {
    const snapshot = entitlementSnapshotFromCustomerInfo(
      customerInfo(),
      "pro",
      USER_ID,
      NOW,
    );
    expect(snapshot.status).toBe("active");
    expect(canExportWithEntitlement(snapshot, NOW)).toBe(true);
  });

  it("blocks a free customer without the Pro entitlement", () => {
    const snapshot = entitlementSnapshotFromCustomerInfo(
      {
        requestDate: new Date(NOW).toISOString(),
        entitlements: { all: {}, active: {} },
      },
      "pro",
      USER_ID,
      NOW,
    );
    expect(snapshot.status).toBe("inactive");
    expect(canExportWithEntitlement(snapshot, NOW)).toBe(false);
  });

  it("blocks stale state even if the cached entitlement was active", () => {
    const snapshot = entitlementSnapshotFromCustomerInfo(
      customerInfo({ checkedAtMs: NOW - ENTITLEMENT_MAX_AGE_MS - 1 }),
      "pro",
      USER_ID,
      NOW,
    );
    expect(snapshot.status).toBe("stale");
    expect(canExportWithEntitlement(snapshot, NOW)).toBe(false);
  });

  it("blocks expired and inactive entitlements", () => {
    const expired = entitlementSnapshotFromCustomerInfo(
      customerInfo({ expiresAtMs: NOW - 1 }),
      "pro",
      USER_ID,
      NOW,
    );
    const inactive = entitlementSnapshotFromCustomerInfo(
      customerInfo({ active: false }),
      "pro",
      USER_ID,
      NOW,
    );
    expect(expired.status).toBe("inactive");
    expect(inactive.status).toBe("inactive");
    expect(canExportWithEntitlement(expired, NOW)).toBe(false);
    expect(canExportWithEntitlement(inactive, NOW)).toBe(false);
  });

  it("fails closed when trusted entitlement verification fails", () => {
    const snapshot = entitlementSnapshotFromCustomerInfo(
      customerInfo({ verification: "FAILED" }),
      "pro",
      USER_ID,
      NOW,
    );
    expect(snapshot.status).toBe("error");
    expect(canExportWithEntitlement(snapshot, NOW)).toBe(false);
  });

  it("fails closed for missing configuration, sign-out, loading, and errors", () => {
    for (const status of ["unconfigured", "signed_out", "loading"] as const) {
      expect(canExportWithEntitlement(initialEntitlementSnapshot(status), NOW)).toBe(
        false,
      );
    }
    expect(
      canExportWithEntitlement(
        {
          ...initialEntitlementSnapshot("loading"),
          status: "error",
          message: "network error",
        },
        NOW,
      ),
    ).toBe(false);
  });
});
