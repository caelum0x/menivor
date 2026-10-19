/**
 * Guest-account claim. Visitors render with a zero-signup DEVICE session whose
 * key lives only in this browser (`src/shared/device/session.ts`). Once they
 * create or sign in to a real account, the Clerk credential takes priority and
 * the guest's reels + remaining credits would otherwise become unreachable.
 *
 * `claimGuestAccount` asks the API to fold the device account into the signed-
 * in account: POST /auth/device/claim, authorized by the Clerk token and
 * proving device ownership with the install id + device key.
 */

import { ApiError, apiRequest } from "@/src/shared/api";
import {
  clearDeviceApiKey,
  getInstallId,
  getStoredDeviceApiKey,
} from "@/src/shared/device/session";
import { getMe } from "@/lib/api";
import type { Me } from "@/lib/types";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

const CLAIM_SETTLED_KEY = "menivor.device.claim_settled";

export interface GuestClaimResult {
  readonly moved_jobs: number;
  readonly moved_credits: number;
}

export type GuestClaimOutcome =
  | { readonly kind: "claimed"; readonly result: GuestClaimResult }
  | { readonly kind: "unsupported" }
  | { readonly kind: "error"; readonly message: string };

function readFlag(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(CLAIM_SETTLED_KEY) ?? "";
  } catch {
    return "";
  }
}

function writeFlag(value: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(CLAIM_SETTLED_KEY, value);
  } catch {
    // Storage unavailable: the prompt may reappear, which is harmless.
  }
}

/** True when this browser holds a guest session that has not been settled. */
export function hasUnclaimedGuestSession(): boolean {
  const key = getStoredDeviceApiKey();
  return key.length > 0 && readFlag() !== key.slice(-16);
}

/** Record that the user resolved (claimed or dismissed) this guest session. */
export function markGuestSessionSettled(): void {
  const key = getStoredDeviceApiKey();
  if (key) writeFlag(key.slice(-16));
}

/**
 * The guest account's own `/me` (reels + credits), read with the DEVICE key
 * (no Clerk token is passed, so the transport falls back to it). Returns null
 * when there is no stored guest key — never mints a fresh device session.
 */
export async function getGuestSnapshot(): Promise<Me | null> {
  if (!getStoredDeviceApiKey()) return null;
  try {
    return await getMe();
  } catch {
    return null;
  }
}

function toCount(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

export async function claimGuestAccount(
  token: string | undefined,
): Promise<GuestClaimOutcome> {
  const deviceKey = getStoredDeviceApiKey();
  if (!deviceKey) {
    return { kind: "error", message: "No guest session found in this browser." };
  }
  if (!token) {
    return { kind: "error", message: "Sign in first, then move your guest reels." };
  }
  try {
    const data = await apiRequest<Partial<GuestClaimResult>>(
      "/auth/device/claim",
      {
        method: "POST",
        body: { install_id: getInstallId(), device_api_key: deviceKey },
        options: { token },
      },
    );
    markGuestSessionSettled();
    // The device account is now empty/merged: drop its key so the browser
    // stops falling back to it. The install id is kept (idempotent re-claim).
    clearDeviceApiKey();
    return {
      kind: "claimed",
      result: {
        moved_jobs: toCount(data?.moved_jobs),
        moved_credits: toCount(data?.moved_credits),
      },
    };
  } catch (err) {
    if (err instanceof ApiError && (err.status === 404 || err.status === 405)) {
      return { kind: "unsupported" };
    }
    return {
      kind: "error",
      message:
        friendlyErrorMessage(err, "Couldn't move your guest reels."),
    };
  }
}
