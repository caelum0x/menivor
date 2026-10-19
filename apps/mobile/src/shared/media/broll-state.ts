/**
 * Shared device-local cache for B-roll history and reel attachment.
 *
 * The API remains authoritative, but caching the latest snapshots gives the
 * studio an immediate history after an app restart or a temporary network
 * outage. The selected clip for the reel composer is stored separately so a
 * tab switch/background restart does not silently drop the attachment.
 */

import * as FileSystem from "expo-file-system/legacy";

import type { BrollGeneration } from "@/lib/types";

import {
  ensureLocalFolderMigrated,
  localFolderUri,
  resolveLocalRead,
} from "./local-folder";

const CACHE_VERSION = 1;
const MAX_CACHED_GENERATIONS = 50;

interface CachedHistory {
  version: number;
  generations: BrollGeneration[];
}

interface CachedReelAttachment {
  version: number;
  broll_intro_key: string | null;
}

function sessionNamespace(token?: string): string {
  // FNV-1a is only a non-reversible filename namespace; no credential is stored.
  let hash = 0x811c9dc5;
  for (const char of token ?? "signed-out") {
    hash ^= char.charCodeAt(0);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

/** File name relative to the app folder (`<documents>/menivor/`). */
function stateFile(kind: "broll-history" | "reel-attachment", token?: string) {
  return `${kind}-${sessionNamespace(token)}.json`;
}

async function ensureDirectory(): Promise<string | null> {
  const base = localFolderUri();
  if (!base) return null;
  await ensureLocalFolderMigrated();
  const info = await FileSystem.getInfoAsync(base);
  if (!info.exists) {
    await FileSystem.makeDirectoryAsync(base, { intermediates: true });
  }
  return base;
}

async function readJson(file: string): Promise<unknown> {
  try {
    // Menivor folder first, then the legacy reelforge/ folder as a fallback.
    const path = await resolveLocalRead(file);
    if (!path) return null;
    return JSON.parse(await FileSystem.readAsStringAsync(path)) as unknown;
  } catch {
    return null;
  }
}

async function writeJson(file: string, value: unknown): Promise<void> {
  const base = await ensureDirectory();
  if (!base) return;
  await FileSystem.writeAsStringAsync(`${base}${file}`, JSON.stringify(value));
}

function isGeneration(value: unknown): value is BrollGeneration {
  if (!value || typeof value !== "object") return false;
  const row = value as Partial<BrollGeneration>;
  return (
    typeof row.generation_id === "string" &&
    typeof row.state === "number" &&
    typeof row.progress === "number" &&
    typeof row.broll_key === "string"
  );
}

export async function loadBrollHistory(
  token?: string,
): Promise<BrollGeneration[]> {
  const value = await readJson(stateFile("broll-history", token));
  if (!value || typeof value !== "object") return [];
  const cache = value as Partial<CachedHistory>;
  if (cache.version !== CACHE_VERSION || !Array.isArray(cache.generations)) {
    return [];
  }
  return cache.generations.filter(isGeneration).slice(0, MAX_CACHED_GENERATIONS);
}

export async function saveBrollHistory(
  token: string | undefined,
  generations: readonly BrollGeneration[],
): Promise<void> {
  const cache: CachedHistory = {
    version: CACHE_VERSION,
    generations: generations.slice(0, MAX_CACHED_GENERATIONS),
  };
  try {
    await writeJson(stateFile("broll-history", token), cache);
  } catch {
    // The server history remains authoritative if device storage is unavailable.
  }
}

export async function loadAttachedBrollKey(
  token?: string,
): Promise<string | null> {
  const value = await readJson(stateFile("reel-attachment", token));
  if (!value || typeof value !== "object") return null;
  const cache = value as Partial<CachedReelAttachment>;
  if (cache.version !== CACHE_VERSION) return null;
  return typeof cache.broll_intro_key === "string" && cache.broll_intro_key.trim()
    ? cache.broll_intro_key
    : null;
}

export async function saveAttachedBrollKey(
  token: string | undefined,
  key: string | null,
): Promise<void> {
  const attachment: CachedReelAttachment = {
    version: CACHE_VERSION,
    broll_intro_key: key?.trim() || null,
  };
  try {
    await writeJson(stateFile("reel-attachment", token), attachment);
  } catch {
    // The in-memory selection still works for the current session.
  }
}
