/**
 * Device-local library of generated narration scripts for the Script Studio.
 *
 * The `POST /api/v1/scripts` endpoint is stateless — it generates a script and
 * returns it, but never persists anything. So the studio keeps the creator's
 * scripts here: generate one, save it, come back later to edit/refine it, then
 * hand it to a reel. Scripts are stored as a single JSON array under one
 * AsyncStorage key (script counts are tiny; this avoids multi-key coordination),
 * mirroring the reel-drafts store.
 *
 * The storage backend is injected (defaulting to AsyncStorage) so the CRUD
 * logic is unit-testable in a plain Node environment without native modules.
 * All reads are fail-safe: a corrupt or absent payload yields an empty list
 * rather than throwing.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";

const SCRIPTS_KEY = "menivor.scriptLibrary.v1";

/** A saved narration script plus the brief it was generated from. */
export interface SavedScript {
  /** Stable client id (never sent to the server). */
  readonly id: string;
  /** What the script is about — the creator's brief. */
  readonly subject: string;
  /** Narration language code the script was generated for. */
  readonly language: string;
  /** How many paragraphs were requested (1..10). */
  readonly paragraphs: number;
  /** Optional style instruction used when generating. */
  readonly prompt: string;
  /** The narration text (editable by the creator). */
  readonly script: string;
  /** ms epoch the script was first saved. */
  readonly createdAt: number;
  /** ms epoch of the last edit. */
  readonly updatedAt: number;
}

/** Fields a caller provides when saving; id/timestamps are assigned. */
export type NewSavedScript = Omit<
  SavedScript,
  "id" | "createdAt" | "updatedAt"
>;

/** The mutable fields an edit may patch. */
export type ScriptPatch = Partial<
  Pick<SavedScript, "subject" | "language" | "paragraphs" | "prompt" | "script">
>;

/** Minimal AsyncStorage surface so tests can inject an in-memory backend. */
export interface ScriptStorage {
  getItem(key: string): Promise<string | null>;
  setItem(key: string, value: string): Promise<void>;
  removeItem(key: string): Promise<void>;
}

function defaultStorage(): ScriptStorage {
  return AsyncStorage as unknown as ScriptStorage;
}

/** Narrow an unknown parsed value to a well-formed saved script, else null. */
function coerceScript(value: unknown): SavedScript | null {
  if (typeof value !== "object" || value === null) return null;
  const s = value as Record<string, unknown>;
  if (typeof s.id !== "string" || s.id.length === 0) return null;
  if (typeof s.subject !== "string") return null;
  if (typeof s.script !== "string") return null;
  if (typeof s.createdAt !== "number") return null;

  const updatedAt =
    typeof s.updatedAt === "number" ? s.updatedAt : s.createdAt;
  const paragraphs =
    typeof s.paragraphs === "number" && Number.isFinite(s.paragraphs)
      ? s.paragraphs
      : 1;

  return {
    id: s.id,
    subject: s.subject,
    language: typeof s.language === "string" ? s.language : "auto",
    paragraphs,
    prompt: typeof s.prompt === "string" ? s.prompt : "",
    script: s.script,
    createdAt: s.createdAt,
    updatedAt,
  };
}

/**
 * List saved scripts, most-recently-edited first. Never throws — a missing or
 * corrupt payload yields an empty list.
 */
export async function listSavedScripts(
  storage: ScriptStorage = defaultStorage(),
): Promise<SavedScript[]> {
  let raw: string | null;
  try {
    raw = await storage.getItem(SCRIPTS_KEY);
  } catch {
    return [];
  }
  if (!raw) return [];

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(parsed)) return [];

  const scripts = parsed
    .map(coerceScript)
    .filter((s): s is SavedScript => s !== null);
  return [...scripts].sort((a, b) => b.updatedAt - a.updatedAt);
}

/** Fetch a single saved script by id, or null when absent. */
export async function getSavedScript(
  id: string,
  storage: ScriptStorage = defaultStorage(),
): Promise<SavedScript | null> {
  const all = await listSavedScripts(storage);
  return all.find((s) => s.id === id) ?? null;
}

function makeId(): string {
  return `script-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * Persist a new script and return it (with its assigned id/timestamps). The
 * returned list ordering is handled by {@link listSavedScripts}.
 */
export async function saveScript(
  input: NewSavedScript,
  storage: ScriptStorage = defaultStorage(),
): Promise<SavedScript> {
  const existing = await listSavedScripts(storage);
  const now = Date.now();
  const script: SavedScript = {
    ...input,
    id: makeId(),
    createdAt: now,
    updatedAt: now,
  };
  await storage.setItem(SCRIPTS_KEY, JSON.stringify([script, ...existing]));
  return script;
}

/**
 * Apply an immutable patch to a saved script, bumping `updatedAt`. Returns the
 * updated script, or null when the id is unknown (a no-op).
 */
export async function updateSavedScript(
  id: string,
  patch: ScriptPatch,
  storage: ScriptStorage = defaultStorage(),
): Promise<SavedScript | null> {
  const existing = await listSavedScripts(storage);
  const target = existing.find((s) => s.id === id);
  if (!target) return null;

  const updated: SavedScript = {
    ...target,
    ...patch,
    updatedAt: Date.now(),
  };
  const next = existing.map((s) => (s.id === id ? updated : s));
  await storage.setItem(SCRIPTS_KEY, JSON.stringify(next));
  return updated;
}

/** Delete a script by id. Removing a missing id is a no-op (idempotent). */
export async function deleteSavedScript(
  id: string,
  storage: ScriptStorage = defaultStorage(),
): Promise<SavedScript[]> {
  const existing = await listSavedScripts(storage);
  const next = existing.filter((s) => s.id !== id);
  await storage.setItem(SCRIPTS_KEY, JSON.stringify(next));
  return next;
}
