/**
 * Device-local store for the pre-render cost estimator.
 *
 * Two small AsyncStorage-backed slices survive the trip between the Model
 * Catalog (compare / detail) and the estimate screen, and from there into the
 * compose/create flow:
 *
 *   - A {@link QuoteDraft}: the stage -> catalog `model_id` map the creator is
 *     assembling (plus an optional profile slug and a budget cap) before they
 *     ask the server for a price.
 *   - The last signed {@link GenerationQuote} returned by the server, so the
 *     Create screen can show the estimated cost of the current model choices.
 *
 * All reads are fail-safe (a missing/corrupt payload yields an empty value) and
 * all writes are immutable (a new object is persisted every time). Mirrors the
 * conventions in `lib/catalog.ts`.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";
import { useCallback, useEffect, useState } from "react";

import type { GenerationQuote } from "@/lib/marketplace";

const DRAFT_KEY = "menivor.modelQuoteDraft.v1";
const LAST_QUOTE_KEY = "menivor.modelQuoteLast.v1";

/**
 * The stage map a creator is building for an estimate. `stages` maps a pipeline
 * stage name (e.g. "voice", "avatar") to a catalog `model_id`. `profile` and
 * `maxCostUsd` are optional overrides passed straight to the quote endpoint.
 */
export interface QuoteDraft {
  readonly stages: Readonly<Record<string, string>>;
  readonly profile?: string;
  readonly maxCostUsd?: string;
}

const EMPTY_DRAFT: QuoteDraft = { stages: {} };

/** Minimal AsyncStorage surface so the store is unit-testable in plain Node. */
export interface QuoteStorage {
  getItem(key: string): Promise<string | null>;
  setItem(key: string, value: string): Promise<void>;
  removeItem(key: string): Promise<void>;
}

function defaultStorage(): QuoteStorage {
  return AsyncStorage as unknown as QuoteStorage;
}

/** Narrow an unknown parsed value into a well-formed draft (drops junk). */
function coerceDraft(value: unknown): QuoteDraft {
  if (typeof value !== "object" || value === null) return EMPTY_DRAFT;
  const raw = value as Record<string, unknown>;

  const stages: Record<string, string> = {};
  if (typeof raw.stages === "object" && raw.stages !== null) {
    for (const [key, val] of Object.entries(raw.stages as Record<string, unknown>)) {
      if (typeof key === "string" && key.length > 0 && typeof val === "string" && val.length > 0) {
        stages[key] = val;
      }
    }
  }

  const profile =
    typeof raw.profile === "string" && raw.profile.length > 0 ? raw.profile : undefined;
  const maxCostUsd =
    typeof raw.maxCostUsd === "string" && raw.maxCostUsd.length > 0 ? raw.maxCostUsd : undefined;

  return {
    stages,
    ...(profile ? { profile } : {}),
    ...(maxCostUsd ? { maxCostUsd } : {}),
  };
}

/** Read the persisted draft. Never throws — yields an empty draft on any failure. */
export async function getQuoteDraft(
  storage: QuoteStorage = defaultStorage(),
): Promise<QuoteDraft> {
  let raw: string | null;
  try {
    raw = await storage.getItem(DRAFT_KEY);
  } catch {
    return EMPTY_DRAFT;
  }
  if (!raw) return EMPTY_DRAFT;
  try {
    return coerceDraft(JSON.parse(raw));
  } catch {
    return EMPTY_DRAFT;
  }
}

async function persistDraft(draft: QuoteDraft, storage: QuoteStorage): Promise<QuoteDraft> {
  await storage.setItem(DRAFT_KEY, JSON.stringify(draft));
  return draft;
}

/** Immutably set (or override) one stage's model and persist the new draft. */
export async function addStageToDraft(
  stage: string,
  modelId: string,
  storage: QuoteStorage = defaultStorage(),
): Promise<QuoteDraft> {
  const trimmedStage = stage.trim();
  const trimmedModel = modelId.trim();
  if (!trimmedStage || !trimmedModel) return getQuoteDraft(storage);
  const current = await getQuoteDraft(storage);
  const next: QuoteDraft = {
    ...current,
    stages: { ...current.stages, [trimmedStage]: trimmedModel },
  };
  return persistDraft(next, storage);
}

/** Immutably remove one stage from the draft and persist the result. */
export async function removeStageFromDraft(
  stage: string,
  storage: QuoteStorage = defaultStorage(),
): Promise<QuoteDraft> {
  const current = await getQuoteDraft(storage);
  if (!(stage in current.stages)) return current;
  const nextStages: Record<string, string> = {};
  for (const [key, val] of Object.entries(current.stages)) {
    if (key !== stage) nextStages[key] = val;
  }
  return persistDraft({ ...current, stages: nextStages }, storage);
}

/** Immutably merge scalar draft fields (profile, budget) and persist. */
export async function patchQuoteDraft(
  patch: { profile?: string; maxCostUsd?: string },
  storage: QuoteStorage = defaultStorage(),
): Promise<QuoteDraft> {
  const current = await getQuoteDraft(storage);
  const next: QuoteDraft = {
    stages: current.stages,
    profile: patch.profile !== undefined ? patch.profile || undefined : current.profile,
    maxCostUsd:
      patch.maxCostUsd !== undefined ? patch.maxCostUsd || undefined : current.maxCostUsd,
  };
  return persistDraft(next, storage);
}

/** Clear the entire draft. Idempotent. */
export async function clearQuoteDraft(
  storage: QuoteStorage = defaultStorage(),
): Promise<void> {
  await storage.removeItem(DRAFT_KEY);
}

/** Persist the last server-signed quote so compose/create can display it. */
export async function saveLastQuote(
  quote: GenerationQuote,
  storage: QuoteStorage = defaultStorage(),
): Promise<void> {
  await storage.setItem(LAST_QUOTE_KEY, JSON.stringify(quote));
}

/** Read the last persisted quote, or null if none / corrupt. */
export async function getLastQuote(
  storage: QuoteStorage = defaultStorage(),
): Promise<GenerationQuote | null> {
  let raw: string | null;
  try {
    raw = await storage.getItem(LAST_QUOTE_KEY);
  } catch {
    return null;
  }
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (typeof parsed !== "object" || parsed === null) return null;
    const quote = parsed as GenerationQuote;
    if (typeof quote.quote_id !== "string" || !Array.isArray(quote.stages)) return null;
    return quote;
  } catch {
    return null;
  }
}

/** Clear the last persisted quote. Idempotent. */
export async function clearLastQuote(
  storage: QuoteStorage = defaultStorage(),
): Promise<void> {
  await storage.removeItem(LAST_QUOTE_KEY);
}

/**
 * React hook exposing the persisted quote draft plus immutable mutators. Loads
 * once on mount; every mutator persists and updates the in-memory copy.
 */
export function useQuoteDraft(): {
  draft: QuoteDraft;
  ready: boolean;
  addStage: (stage: string, modelId: string) => Promise<void>;
  removeStage: (stage: string) => Promise<void>;
  patch: (patch: { profile?: string; maxCostUsd?: string }) => Promise<void>;
  clear: () => Promise<void>;
  reload: () => Promise<void>;
} {
  const [draft, setDraft] = useState<QuoteDraft>(EMPTY_DRAFT);
  const [ready, setReady] = useState(false);

  const reload = useCallback(async () => {
    const loaded = await getQuoteDraft();
    setDraft(loaded);
    setReady(true);
  }, []);

  useEffect(() => {
    let active = true;
    void getQuoteDraft().then((loaded) => {
      if (active) {
        setDraft(loaded);
        setReady(true);
      }
    });
    return () => {
      active = false;
    };
  }, []);

  const addStage = useCallback(async (stage: string, modelId: string) => {
    setDraft(await addStageToDraft(stage, modelId));
  }, []);

  const removeStage = useCallback(async (stage: string) => {
    setDraft(await removeStageFromDraft(stage));
  }, []);

  const patch = useCallback(async (next: { profile?: string; maxCostUsd?: string }) => {
    setDraft(await patchQuoteDraft(next));
  }, []);

  const clear = useCallback(async () => {
    await clearQuoteDraft();
    setDraft(EMPTY_DRAFT);
  }, []);

  return { draft, ready, addStage, removeStage, patch, clear, reload };
}

/**
 * React hook exposing the last persisted quote. Reloads on demand (e.g. via
 * `useFocusEffect`) so a Create screen reflects a freshly-computed estimate.
 */
export function useLastQuote(): {
  quote: GenerationQuote | null;
  ready: boolean;
  reload: () => Promise<void>;
} {
  const [quote, setQuote] = useState<GenerationQuote | null>(null);
  const [ready, setReady] = useState(false);

  const reload = useCallback(async () => {
    const loaded = await getLastQuote();
    setQuote(loaded);
    setReady(true);
  }, []);

  useEffect(() => {
    let active = true;
    void getLastQuote().then((loaded) => {
      if (active) {
        setQuote(loaded);
        setReady(true);
      }
    });
    return () => {
      active = false;
    };
  }, []);

  return { quote, ready, reload };
}
