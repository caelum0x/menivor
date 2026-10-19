/**
 * Device-local app folder (`<documents>/menivor/`) bound to expo-file-system,
 * with the one-time move from the legacy `<documents>/reelforge/` folder.
 * Every reader/writer awaits `ensureLocalFolderMigrated()` first, so the move
 * always happens before the first access; the root layout also starts it at
 * launch so it is usually finished before any screen needs local state.
 */

import * as FileSystem from "expo-file-system/legacy";

import {
  LOCAL_FOLDER,
  migrateLegacyFolder,
  migratedUri,
  readCandidates,
  type MigrationFs,
  type MigrationResult,
} from "./local-folder-migration";

const expoFs: MigrationFs = {
  async exists(uri) {
    const info = await FileSystem.getInfoAsync(uri);
    return { exists: info.exists, isDirectory: info.exists && info.isDirectory };
  },
  list: (dirUri) => FileSystem.readDirectoryAsync(dirUri),
  move: (from, to) => FileSystem.moveAsync({ from, to }),
  makeDir: (uri) => FileSystem.makeDirectoryAsync(uri, { intermediates: true }),
  remove: (uri) => FileSystem.deleteAsync(uri, { idempotent: true }),
};

let migration: Promise<MigrationResult> | null = null;

/** Run the legacy-folder move once per app process (safe to call repeatedly). */
export function ensureLocalFolderMigrated(): Promise<MigrationResult> {
  if (!migration) {
    const documents = FileSystem.documentDirectory;
    migration = documents
      ? migrateLegacyFolder(expoFs, documents).then((result) => {
          if (result.outcome === "partial") {
            console.warn("[menivor] local folder migration incomplete", result);
          }
          return result;
        })
      : Promise.resolve({ outcome: "nothing-to-migrate", moved: 0, failed: 0 });
  }
  return migration;
}

/** `<documents>/menivor/` (with trailing slash), or "" when storage is unavailable. */
export function localFolderUri(): string {
  const documents = FileSystem.documentDirectory;
  return documents ? `${documents}${LOCAL_FOLDER}/` : "";
}

/**
 * The first existing location of `relativePath` (Menivor folder, then the legacy
 * folder), or null when neither exists.
 */
export async function resolveLocalRead(relativePath: string): Promise<string | null> {
  const documents = FileSystem.documentDirectory;
  if (!documents) return null;
  await ensureLocalFolderMigrated();
  for (const candidate of readCandidates(documents, relativePath)) {
    try {
      const info = await FileSystem.getInfoAsync(candidate);
      if (info.exists) return candidate;
    } catch {
      // Try the next candidate.
    }
  }
  return null;
}

/** Remap a pre-migration `reelforge/` file URI to its `menivor/` location. */
export function currentLocalUri(uri: string): string {
  const documents = FileSystem.documentDirectory;
  return documents ? migratedUri(documents, uri) : uri;
}
