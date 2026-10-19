/**
 * Web device-session auth for the Menivor API.
 *
 * The backend's `POST /auth/device` exchanges a high-entropy install id for a
 * per-installation API key (and grants the free signup credits on first
 * exchange). On web the "installation" is this browser profile: a random
 * install id is minted once, persisted in localStorage, and re-exchanging it
 * always restores the same account — so the api_key itself is recoverable and
 * safe to keep client-side (it is scoped to this synthetic device account).
 *
 * Every API call then sends the key as `x-api-key` (see `src/shared/api/
 * client.ts`, which falls back to this store whenever no explicit Clerk token
 * is supplied). This gives visitors a working create->render->preview loop
 * with zero signup, exactly like the mobile app's first-run flow.
 */

import { API_BASE } from "../api/base";

const INSTALL_ID_KEY = "menivor.device.install_id";
const API_KEY_KEY = "menivor.device.api_key";
const USER_ID_KEY = "menivor.device.user_id";

/**
 * The live API only enrolls `ios` | `android` platforms today; web sessions
 * enroll under `android` until the backend adds a `web` platform. The value
 * only namespaces the derived account — it has no functional effect.
 */
const DEVICE_PLATFORM = "android";

export interface DeviceSession {
  api_key: string;
  created: boolean;
  credits: number;
  user_id: string;
}

function isBrowser(): boolean {
  return typeof window !== "undefined" && !!window.localStorage;
}

function readStorage(key: string): string {
  if (!isBrowser()) return "";
  try {
    return window.localStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

function writeStorage(key: string, value: string): void {
  if (!isBrowser()) return;
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Storage full / privacy mode: the session simply won't persist.
  }
}

function removeStorage(key: string): void {
  if (!isBrowser()) return;
  try {
    window.localStorage.removeItem(key);
  } catch {
    // Ignore: worst case a stale value lingers until the next write.
  }
}

/** Mint a high-entropy install id matching the API's `[A-Za-z0-9._:-]{20,200}`. */
function mintInstallId(): string {
  const uuid = (): string => {
    if (typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }
    // Older browsers: 128 bits from getRandomValues, hex-encoded.
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  };
  return `web-${uuid()}-${uuid()}`.slice(0, 120);
}

/** The persisted install id for this browser profile, minting one on demand. */
export function getInstallId(): string {
  const existing = readStorage(INSTALL_ID_KEY);
  if (existing.length >= 20) return existing;
  const minted = mintInstallId();
  writeStorage(INSTALL_ID_KEY, minted);
  return minted;
}

/** The stored device API key, or "" when none has been provisioned yet. */
export function getStoredDeviceApiKey(): string {
  return readStorage(API_KEY_KEY);
}

/** The stored device account user id, or "" when unknown. */
export function getStoredDeviceUserId(): string {
  return readStorage(USER_ID_KEY);
}

/** Drop the stored key (install id is kept: re-exchange restores the account). */
export function clearDeviceApiKey(): void {
  removeStorage(API_KEY_KEY);
  removeStorage(USER_ID_KEY);
}

async function exchangeDeviceSession(): Promise<DeviceSession> {
  const body = JSON.stringify({
    install_id: getInstallId(),
    platform: DEVICE_PLATFORM,
  });
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/auth/device`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      cache: "no-store",
    });
  } catch (error) {
    throw new Error(
      `Could not reach the Menivor API to start a session: ${
        error instanceof Error ? error.message : String(error)
      }`,
    );
  }

  const raw = await response.text();
  type Envelope = { data?: DeviceSession; message?: string | null };
  let envelope: Envelope | null = null;
  try {
    envelope = JSON.parse(raw) as Envelope;
  } catch {
    envelope = null;
  }
  if (!response.ok || !envelope?.data?.api_key) {
    throw new Error(
      envelope?.message ||
        `Device session request failed (HTTP ${response.status}).`,
    );
  }

  const session = envelope.data;
  writeStorage(API_KEY_KEY, session.api_key);
  writeStorage(USER_ID_KEY, session.user_id);
  return session;
}

let inflight: Promise<DeviceSession> | null = null;

/**
 * Ensure this browser has a device session, exchanging the install id when no
 * key is stored yet. Single-flight: concurrent callers share one exchange.
 * Returns the session (from storage it returns a synthetic snapshot with only
 * the key populated — callers needing fresh credits should hit `/me`).
 */
export function ensureDeviceSession(): Promise<DeviceSession> {
  if (!isBrowser()) {
    return Promise.reject(
      new Error("Device sessions are only available in the browser."),
    );
  }
  const stored = getStoredDeviceApiKey();
  if (stored) {
    return Promise.resolve({
      api_key: stored,
      created: false,
      credits: -1,
      user_id: getStoredDeviceUserId(),
    });
  }
  if (!inflight) {
    inflight = exchangeDeviceSession().finally(() => {
      inflight = null;
    });
  }
  return inflight;
}

/**
 * Force a fresh exchange (used after a 401 with a device key — e.g. the
 * server rotated its device secret). Replaces the stored key.
 */
export function refreshDeviceSession(): Promise<DeviceSession> {
  if (!isBrowser()) {
    return Promise.reject(
      new Error("Device sessions are only available in the browser."),
    );
  }
  if (!inflight) {
    clearDeviceApiKey();
    inflight = exchangeDeviceSession().finally(() => {
      inflight = null;
    });
  }
  return inflight;
}
