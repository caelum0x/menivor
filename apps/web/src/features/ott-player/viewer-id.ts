/** A random per-browser id so stream limits count screens, not people. Stored locally; never sent elsewhere. */
const KEY = "menivor.ott.viewer";

export function viewerId(store: Pick<Storage, "getItem" | "setItem"> | undefined = globalThis.localStorage): string {
  const existing = store?.getItem(KEY);
  if (existing) return existing;
  const fresh = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  store?.setItem(KEY, fresh);
  return fresh;
}
