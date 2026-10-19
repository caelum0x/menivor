/**
 * Device-local persistence for the navigation hub: recently-opened screens and
 * pinned (favourite) screens. Backed by AsyncStorage so the hub can surface a
 * personal shortcut row without any backend round-trip.
 *
 * All functions are immutable: they read the stored array, compute a NEW array,
 * persist it, and return it. Reads fail open (return []), so a storage error
 * never blanks the hub.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";

const RECENTS_KEY = "nav.recents.v1";
const PINS_KEY = "nav.pins.v1";

/** Cap on how many recents we keep — enough for one shortcut row. */
export const MAX_RECENTS = 8;

async function readList(key: string): Promise<readonly string[]> {
  try {
    const raw = await AsyncStorage.getItem(key);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((v): v is string => typeof v === "string");
  } catch {
    return [];
  }
}

async function writeList(key: string, list: readonly string[]): Promise<void> {
  try {
    await AsyncStorage.setItem(key, JSON.stringify(list));
  } catch {
    // Persistence is best-effort; the in-memory result is still returned.
  }
}

/** Load recently-opened routes, most-recent first. */
export function loadRecents(): Promise<readonly string[]> {
  return readList(RECENTS_KEY);
}

/**
 * Record `route` as the most-recently opened screen. De-duplicates and caps the
 * list at {@link MAX_RECENTS}. Returns the new list.
 */
export async function pushRecent(route: string): Promise<readonly string[]> {
  const current = await readList(RECENTS_KEY);
  const next = [route, ...current.filter((r) => r !== route)].slice(
    0,
    MAX_RECENTS,
  );
  await writeList(RECENTS_KEY, next);
  return next;
}

/** Clear the recents list. Returns the empty list. */
export async function clearRecents(): Promise<readonly string[]> {
  await writeList(RECENTS_KEY, []);
  return [];
}

/** Load pinned routes in the order they were pinned. */
export function loadPins(): Promise<readonly string[]> {
  return readList(PINS_KEY);
}

/**
 * Toggle a route's pinned state. Pinning appends to the end; unpinning removes
 * it. Returns the new pin list.
 */
export async function togglePin(route: string): Promise<readonly string[]> {
  const current = await readList(PINS_KEY);
  const next = current.includes(route)
    ? current.filter((r) => r !== route)
    : [...current, route];
  await writeList(PINS_KEY, next);
  return next;
}
