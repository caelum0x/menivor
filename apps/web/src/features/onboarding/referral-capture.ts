/**
 * Pending-referral capture. `/sign-up?ref=CODE` (built by /referral, the
 * insights referral card and the public share page `/r/{token}`) stores the
 * code here BEFORE Clerk takes over, so it survives the sign-up round-trip
 * (email verification, OAuth redirects). Onboarding then redeems it once via
 * POST /me/referral/redeem and clears it.
 */

const PENDING_REFERRAL_KEY = "menivor.referral.pending";

/** Referral codes are short slugs; anything else is ignored. */
const REFERRAL_CODE_PATTERN = /^[A-Za-z0-9_-]{3,64}$/;

export function normalizeReferralCode(raw: string | null | undefined): string {
  const code = (raw ?? "").trim();
  return REFERRAL_CODE_PATTERN.test(code) ? code : "";
}

function storage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function storePendingReferral(raw: string | null | undefined): void {
  const code = normalizeReferralCode(raw);
  if (!code) return;
  try {
    storage()?.setItem(PENDING_REFERRAL_KEY, code);
  } catch {
    // Private mode / quota: the invitee can still enter the code on /referral.
  }
}

export function readPendingReferral(): string {
  try {
    return normalizeReferralCode(storage()?.getItem(PENDING_REFERRAL_KEY));
  } catch {
    return "";
  }
}

export function clearPendingReferral(): void {
  try {
    storage()?.removeItem(PENDING_REFERRAL_KEY);
  } catch {
    // Ignore: a stale code is re-rejected server-side as already redeemed.
  }
}
