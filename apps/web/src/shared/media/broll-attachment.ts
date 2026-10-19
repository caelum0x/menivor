/** Session-scoped durable-key handoff from the B-roll feature to reel-create. */

export interface BrollAttachment {
  key: string;
  resultUrl: string;
}

const STORAGE_KEY = "reelforge:broll-attachment";

export function stashBrollAttachment(attachment: BrollAttachment): void {
  if (typeof window === "undefined" || !attachment.key.trim()) return;
  try {
    window.sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        key: attachment.key.trim(),
        resultUrl: attachment.resultUrl.trim(),
      }),
    );
  } catch {
    // The handoff is a convenience; generation history remains authoritative.
  }
}

export function loadBrollAttachment(): BrollAttachment | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    if (typeof parsed.key !== "string" || !parsed.key.trim()) return null;
    return {
      key: parsed.key.trim(),
      resultUrl: typeof parsed.resultUrl === "string" ? parsed.resultUrl : "",
    };
  } catch {
    return null;
  }
}

export function clearBrollAttachment(): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage can be unavailable in hardened/private browser contexts.
  }
}
