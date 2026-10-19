/**
 * Whether AI B-roll can be used by this account right now, from the
 * server-owned GET /pilot/capabilities payload. Pure so the tab bar and the
 * B-roll screen share one rule (and it is unit-tested).
 *
 * Unavailable when the server has not switched B-roll on for the account, or
 * when clip storage is not ready. The tab bar hides the B-roll tab then, so a
 * store build never shows a tab that can only say "unavailable".
 */
function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : null;
}

function storageReady(capabilities: Record<string, unknown>): boolean {
  const runtime = asRecord(asRecord(capabilities.product)?.runtime);
  return runtime?.storage_ready !== false;
}

export function isBrollAvailable(capabilities: unknown): boolean {
  const caps = asRecord(capabilities);
  if (!caps) return false;
  return asRecord(caps.generation)?.broll === true && storageReady(caps);
}
