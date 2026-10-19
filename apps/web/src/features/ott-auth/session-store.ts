/** Channel viewer sessions in local storage, one per channel handle (never in a cookie or a URL). */

const PREFIX = "menivor.ott.viewer.";

export interface StoredSession {
  readonly session: string;
  readonly expiresAt: number;
  readonly name: string;
}

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

export function readSession(handle: string, now = Date.now()): StoredSession | null {
  const raw = storage()?.getItem(PREFIX + handle);
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as StoredSession;
    if (!value.session || value.expiresAt * 1000 <= now) {
      clearSession(handle);
      return null;
    }
    return value;
  } catch {
    clearSession(handle);
    return null;
  }
}

export function writeSession(handle: string, value: StoredSession): void {
  storage()?.setItem(PREFIX + handle, JSON.stringify(value));
}

export function clearSession(handle: string): void {
  storage()?.removeItem(PREFIX + handle);
}
