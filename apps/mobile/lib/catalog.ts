/**
 * Catalog aggregation + a device-local "compose selection" store — Expo.
 *
 * The individual catalog fetchers already live in `lib/api.ts` (they wrap the
 * read-only `GET /catalog/*` and `GET /dub/languages` endpoints). This module
 * re-exports them under one import surface for the catalog browser screens, and
 * adds a small AsyncStorage-backed store so a creator's picks (a caption style,
 * a music track, a layout, a cover style, a starting template, and dub target
 * languages) survive the trip from a catalog gallery back into the compose
 * flow.
 *
 * All reads are fail-safe (a missing/corrupt payload yields an empty selection)
 * and all writes are immutable (a new object is persisted every time).
 */

import AsyncStorage from "@react-native-async-storage/async-storage";
import { useCallback, useEffect, useState } from "react";

export {
  listCaptionStyles,
  listMusic,
  listLayouts,
  listHooks,
  listCoverStyles,
  listDubLanguages,
} from "@/lib/api";
// `listTemplates` in api.ts is the *catalog* template list (distinct from the
// shot-template engine in lib/templates.ts); re-exported under a clear name.
export { listTemplates as listCatalogTemplates } from "@/lib/api";
// The background-footage library lives on the shot-template engine
// (GET /templates/backgrounds), not under /catalog/*; re-exported here so the
// catalog browser screens have a single import surface.
export { listBackgrounds, type BackgroundClip } from "@/lib/templates";

export type {
  CaptionStyle,
  MusicTrack,
  LayoutOption,
  HookCatalog,
  CoverStyle,
  DubLanguage,
  Template as CatalogTemplate,
} from "@/lib/types";

const SELECTION_KEY = "menivor.catalogSelection.v1";

/**
 * A creator's current catalog picks, persisted device-locally. Every field is
 * optional — a fresh install has no selection. `dubLanguages` is a set of
 * language codes (order-insensitive) the creator wants to dub into.
 */
export interface CatalogSelection {
  readonly captionStyle?: string;
  readonly musicId?: string;
  readonly layout?: string;
  readonly coverStyle?: string;
  readonly templateId?: string;
  readonly backgroundId?: string;
  readonly dubLanguages?: readonly string[];
}

/** Minimal AsyncStorage surface so the store is unit-testable in plain Node. */
export interface SelectionStorage {
  getItem(key: string): Promise<string | null>;
  setItem(key: string, value: string): Promise<void>;
  removeItem(key: string): Promise<void>;
}

function defaultStorage(): SelectionStorage {
  return AsyncStorage as unknown as SelectionStorage;
}

/** Narrow an unknown parsed value into a well-formed selection (drops junk). */
function coerceSelection(value: unknown): CatalogSelection {
  if (typeof value !== "object" || value === null) return {};
  const raw = value as Record<string, unknown>;
  const str = (v: unknown): string | undefined =>
    typeof v === "string" && v.length > 0 ? v : undefined;

  const dubLanguages = Array.isArray(raw.dubLanguages)
    ? raw.dubLanguages.filter((c): c is string => typeof c === "string" && c.length > 0)
    : undefined;

  return {
    ...(str(raw.captionStyle) ? { captionStyle: str(raw.captionStyle) } : {}),
    ...(str(raw.musicId) ? { musicId: str(raw.musicId) } : {}),
    ...(str(raw.layout) ? { layout: str(raw.layout) } : {}),
    ...(str(raw.coverStyle) ? { coverStyle: str(raw.coverStyle) } : {}),
    ...(str(raw.templateId) ? { templateId: str(raw.templateId) } : {}),
    ...(str(raw.backgroundId) ? { backgroundId: str(raw.backgroundId) } : {}),
    ...(dubLanguages && dubLanguages.length > 0 ? { dubLanguages } : {}),
  };
}

/** Read the persisted selection. Never throws — yields `{}` on any failure. */
export async function getCatalogSelection(
  storage: SelectionStorage = defaultStorage(),
): Promise<CatalogSelection> {
  let raw: string | null;
  try {
    raw = await storage.getItem(SELECTION_KEY);
  } catch {
    return {};
  }
  if (!raw) return {};
  try {
    return coerceSelection(JSON.parse(raw));
  } catch {
    return {};
  }
}

/**
 * Immutably merge `patch` onto the persisted selection and return the new
 * selection. A field set to `undefined` in `patch` is ignored (use
 * {@link clearCatalogSelection} to reset).
 */
export async function patchCatalogSelection(
  patch: Partial<CatalogSelection>,
  storage: SelectionStorage = defaultStorage(),
): Promise<CatalogSelection> {
  const current = await getCatalogSelection(storage);
  const next: CatalogSelection = { ...current };
  const mutable = next as { [K in keyof CatalogSelection]: CatalogSelection[K] };
  (Object.keys(patch) as Array<keyof CatalogSelection>).forEach((key) => {
    const value = patch[key];
    if (value !== undefined) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (mutable as any)[key] = value;
    }
  });
  await storage.setItem(SELECTION_KEY, JSON.stringify(next));
  return next;
}

/** Clear the entire persisted selection. Idempotent. */
export async function clearCatalogSelection(
  storage: SelectionStorage = defaultStorage(),
): Promise<void> {
  await storage.removeItem(SELECTION_KEY);
}

/**
 * Toggle a dub-target language code in the persisted selection and return the
 * new selection. Adding when absent, removing when present.
 */
export async function toggleDubLanguage(
  code: string,
  storage: SelectionStorage = defaultStorage(),
): Promise<CatalogSelection> {
  const current = await getCatalogSelection(storage);
  const set = new Set(current.dubLanguages ?? []);
  if (set.has(code)) {
    set.delete(code);
  } else {
    set.add(code);
  }
  const dubLanguages = [...set];
  const next: CatalogSelection = { ...current, dubLanguages };
  await storage.setItem(SELECTION_KEY, JSON.stringify(next));
  return next;
}

/**
 * React hook exposing the persisted selection plus immutable mutators. Loads
 * once on mount; every mutator persists and updates the in-memory copy so any
 * catalog screen reflects the current picks without a manual reload.
 */
export function useCatalogSelection(): {
  selection: CatalogSelection;
  ready: boolean;
  patch: (patch: Partial<CatalogSelection>) => Promise<void>;
  toggleDub: (code: string) => Promise<void>;
  clear: () => Promise<void>;
  reload: () => Promise<void>;
} {
  const [selection, setSelection] = useState<CatalogSelection>({});
  const [ready, setReady] = useState(false);

  const reload = useCallback(async () => {
    const loaded = await getCatalogSelection();
    setSelection(loaded);
    setReady(true);
  }, []);

  useEffect(() => {
    let active = true;
    (async () => {
      const loaded = await getCatalogSelection();
      if (active) {
        setSelection(loaded);
        setReady(true);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const patch = useCallback(async (next: Partial<CatalogSelection>) => {
    const updated = await patchCatalogSelection(next);
    setSelection(updated);
  }, []);

  const toggleDub = useCallback(async (code: string) => {
    const updated = await toggleDubLanguage(code);
    setSelection(updated);
  }, []);

  const clear = useCallback(async () => {
    await clearCatalogSelection();
    setSelection({});
  }, []);

  return { selection, ready, patch, toggleDub, clear, reload };
}
