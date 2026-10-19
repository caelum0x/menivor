/**
 * Device-local reel drafts for the waitlist era.
 *
 * Before the generation pipeline is live, a creator can still record or import
 * a clip and jot the brief — we persist that intent locally so it is ready to
 * attach the moment generation turns on. Drafts are stored as a single JSON
 * array under one AsyncStorage key (draft counts are tiny; this avoids
 * multi-key coordination).
 *
 * The storage backend is injected (defaulting to AsyncStorage) so the CRUD
 * logic is unit-testable in a plain Node environment without native modules.
 * All reads are fail-safe: a corrupt or absent payload yields an empty list
 * rather than throwing.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";

const DRAFTS_KEY = "menivor.reelDrafts.v1";

/** A locally-captured clip + brief, awaiting the generation pipeline. */
export interface ReelDraft {
  /** Stable client id (never sent to the server). */
  readonly id: string;
  /** What the reel is about — the creator's brief. */
  readonly subject: string;
  /** ms epoch the draft was saved. */
  readonly createdAt: number;
  /** Local media, when a clip was recorded/imported. */
  readonly media?: {
    readonly uri: string;
    readonly name: string;
    readonly mimeType: string;
    readonly size: number;
  };
  /** Optional caption preset id the creator previewed. */
  readonly captionStyle?: string;
}

/** Fields a caller provides when creating a draft (id/createdAt are assigned). */
export type NewReelDraft = Omit<ReelDraft, "id" | "createdAt">;

/** Minimal AsyncStorage surface so tests can inject an in-memory backend. */
export interface DraftStorage {
  getItem(key: string): Promise<string | null>;
  setItem(key: string, value: string): Promise<void>;
  removeItem(key: string): Promise<void>;
}

function defaultStorage(): DraftStorage {
  return AsyncStorage as unknown as DraftStorage;
}

/** Narrow an unknown parsed value to a well-formed draft, else null. */
function coerceDraft(value: unknown): ReelDraft | null {
  if (typeof value !== "object" || value === null) return null;
  const draft = value as Record<string, unknown>;
  if (typeof draft.id !== "string" || draft.id.length === 0) return null;
  if (typeof draft.subject !== "string") return null;
  if (typeof draft.createdAt !== "number") return null;

  const media = draft.media;
  let normalizedMedia: ReelDraft["media"];
  if (typeof media === "object" && media !== null) {
    const m = media as Record<string, unknown>;
    if (
      typeof m.uri === "string" &&
      typeof m.name === "string" &&
      typeof m.mimeType === "string" &&
      typeof m.size === "number"
    ) {
      normalizedMedia = {
        uri: m.uri,
        name: m.name,
        mimeType: m.mimeType,
        size: m.size,
      };
    }
  }

  return {
    id: draft.id,
    subject: draft.subject,
    createdAt: draft.createdAt,
    ...(normalizedMedia ? { media: normalizedMedia } : {}),
    ...(typeof draft.captionStyle === "string"
      ? { captionStyle: draft.captionStyle }
      : {}),
  };
}

/**
 * List saved drafts, newest first. Never throws — a missing or corrupt payload
 * yields an empty list.
 */
export async function listDrafts(
  storage: DraftStorage = defaultStorage(),
): Promise<ReelDraft[]> {
  let raw: string | null;
  try {
    raw = await storage.getItem(DRAFTS_KEY);
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

  const drafts = parsed
    .map(coerceDraft)
    .filter((d): d is ReelDraft => d !== null);
  return [...drafts].sort((a, b) => b.createdAt - a.createdAt);
}

function makeId(): string {
  return `draft-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * Persist a new draft and return it (with its assigned id/createdAt). The
 * returned list ordering is handled by {@link listDrafts}.
 */
export async function saveDraft(
  input: NewReelDraft,
  storage: DraftStorage = defaultStorage(),
): Promise<ReelDraft> {
  const existing = await listDrafts(storage);
  const draft: ReelDraft = {
    ...input,
    id: makeId(),
    createdAt: Date.now(),
  };
  await storage.setItem(DRAFTS_KEY, JSON.stringify([draft, ...existing]));
  return draft;
}

/** Look up one draft by id, or null when it no longer exists. */
export async function getDraft(
  id: string,
  storage: DraftStorage = defaultStorage(),
): Promise<ReelDraft | null> {
  const drafts = await listDrafts(storage);
  return drafts.find((d) => d.id === id) ?? null;
}

/** Delete a draft by id. Removing a missing id is a no-op (idempotent). */
export async function deleteDraft(
  id: string,
  storage: DraftStorage = defaultStorage(),
): Promise<ReelDraft[]> {
  const existing = await listDrafts(storage);
  const next = existing.filter((d) => d.id !== id);
  await storage.setItem(DRAFTS_KEY, JSON.stringify(next));
  return next;
}
