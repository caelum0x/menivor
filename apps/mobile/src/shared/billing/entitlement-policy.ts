export const PRO_ENTITLEMENT_ID = "pro";
export const ENTITLEMENT_MAX_AGE_MS = 5 * 60 * 1000;

export type EntitlementStatus =
  | "loading"
  | "signed_out"
  | "unconfigured"
  | "active"
  | "inactive"
  | "stale"
  | "error";

export type EntitlementVerification =
  | "verified"
  | "verified_on_device"
  | "not_requested"
  | "failed"
  | "unknown";

export interface EntitlementSnapshot {
  status: EntitlementStatus;
  entitlementId: string;
  appUserId: string | null;
  checkedAtMs: number | null;
  expiresAtMs: number | null;
  verification: EntitlementVerification;
  message: string;
}

export interface RevenueCatEntitlementLike {
  isActive: boolean;
  expirationDate?: string | null;
  expirationDateMillis?: number | null;
  verification?: string;
}

export interface RevenueCatCustomerInfoLike {
  requestDate: string;
  entitlements: {
    all: Record<string, RevenueCatEntitlementLike | undefined>;
    active: Record<string, RevenueCatEntitlementLike | undefined>;
  };
}

function verificationFromSdk(value: string | undefined): EntitlementVerification {
  switch (value) {
    case "VERIFIED":
      return "verified";
    case "VERIFIED_ON_DEVICE":
      return "verified_on_device";
    case "NOT_REQUESTED":
      return "not_requested";
    case "FAILED":
      return "failed";
    default:
      return "unknown";
  }
}

function expirationMillis(
  entitlement: RevenueCatEntitlementLike,
): number | null {
  if (typeof entitlement.expirationDateMillis === "number") {
    return Number.isFinite(entitlement.expirationDateMillis)
      ? entitlement.expirationDateMillis
      : null;
  }
  if (!entitlement.expirationDate) return null;
  const parsed = Date.parse(entitlement.expirationDate);
  return Number.isFinite(parsed) ? parsed : null;
}

export function initialEntitlementSnapshot(
  status: Extract<EntitlementStatus, "loading" | "signed_out" | "unconfigured">,
  entitlementId = PRO_ENTITLEMENT_ID,
  message?: string,
): EntitlementSnapshot {
  const defaultMessage = {
    loading: "Checking Pro access…",
    signed_out: "Sign in before restoring or buying Pro.",
    unconfigured: "RevenueCat is not configured for this build.",
  }[status];

  return {
    status,
    entitlementId,
    appUserId: null,
    checkedAtMs: null,
    expiresAtMs: null,
    verification: "unknown",
    message: message ?? defaultMessage,
  };
}

/**
 * Converts RevenueCat's SDK object into the small, deterministic state used by
 * export policy. SDK objects never cross this boundary.
 */
export function entitlementSnapshotFromCustomerInfo(
  customerInfo: RevenueCatCustomerInfoLike,
  entitlementId: string,
  appUserId: string,
  nowMs = Date.now(),
): EntitlementSnapshot {
  const checkedAtMs = Date.parse(customerInfo.requestDate);
  if (!Number.isFinite(checkedAtMs)) {
    return {
      status: "error",
      entitlementId,
      appUserId,
      checkedAtMs: null,
      expiresAtMs: null,
      verification: "unknown",
      message: "RevenueCat returned an invalid entitlement timestamp.",
    };
  }

  const entitlement =
    customerInfo.entitlements.active[entitlementId] ??
    customerInfo.entitlements.all[entitlementId];

  if (!entitlement) {
    return {
      status:
        nowMs - checkedAtMs > ENTITLEMENT_MAX_AGE_MS ? "stale" : "inactive",
      entitlementId,
      appUserId,
      checkedAtMs,
      expiresAtMs: null,
      verification: "unknown",
      message:
        nowMs - checkedAtMs > ENTITLEMENT_MAX_AGE_MS
          ? "Pro access must be refreshed before export."
          : "Preview is free. Pro is required to export or share.",
    };
  }

  const expiresAtMs = expirationMillis(entitlement);
  const verification = verificationFromSdk(entitlement.verification);
  const expired = expiresAtMs !== null && expiresAtMs <= nowMs;
  const stale =
    checkedAtMs > nowMs + 60_000 ||
    nowMs - checkedAtMs > ENTITLEMENT_MAX_AGE_MS;

  if (verification === "failed") {
    return {
      status: "error",
      entitlementId,
      appUserId,
      checkedAtMs,
      expiresAtMs,
      verification,
      message: "Pro access could not be verified. Refresh before exporting.",
    };
  }

  if (stale) {
    return {
      status: "stale",
      entitlementId,
      appUserId,
      checkedAtMs,
      expiresAtMs,
      verification,
      message: "Pro access must be refreshed before export.",
    };
  }

  if (!entitlement.isActive || expired) {
    return {
      status: "inactive",
      entitlementId,
      appUserId,
      checkedAtMs,
      expiresAtMs,
      verification,
      message: "Preview is free. Pro is required to export or share.",
    };
  }

  return {
    status: "active",
    entitlementId,
    appUserId,
    checkedAtMs,
    expiresAtMs,
    verification,
    message: "Pro export is ready.",
  };
}

/** Export fails closed for missing, stale, expired, or unverifiable state. */
export function canExportWithEntitlement(
  snapshot: EntitlementSnapshot,
  nowMs = Date.now(),
): boolean {
  if (snapshot.status !== "active" || snapshot.checkedAtMs === null) {
    return false;
  }
  if (
    snapshot.checkedAtMs > nowMs + 60_000 ||
    nowMs - snapshot.checkedAtMs > ENTITLEMENT_MAX_AGE_MS
  ) {
    return false;
  }
  if (snapshot.expiresAtMs !== null && snapshot.expiresAtMs <= nowMs) {
    return false;
  }
  return snapshot.verification !== "failed";
}
