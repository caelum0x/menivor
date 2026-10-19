/**
 * Pure (Expo-free) logic for the one-time ReelForge -> Menivor local-folder
 * rename. The app used to keep device-local state under
 * `<documents>/reelforge/`; it now uses `<documents>/menivor/`. On first launch
 * after the update the legacy folder is moved across; anything that cannot be
 * moved stays readable through the legacy fallback paths.
 *
 * The filesystem is injected so the merge rules are unit-testable in Node.
 */

export const LOCAL_FOLDER = "menivor";
export const LEGACY_LOCAL_FOLDER = "reelforge";

/** The subset of expo-file-system the migration needs (all URIs end in "/" for dirs). */
export interface MigrationFs {
  exists(uri: string): Promise<{ exists: boolean; isDirectory: boolean }>;
  list(dirUri: string): Promise<string[]>;
  move(from: string, to: string): Promise<void>;
  makeDir(uri: string): Promise<void>;
  remove(uri: string): Promise<void>;
}

export interface MigrationResult {
  /** "moved": whole folder renamed; "merged": entries merged into an existing folder. */
  readonly outcome: "nothing-to-migrate" | "moved" | "merged" | "partial";
  readonly moved: number;
  readonly failed: number;
}

function withSlash(uri: string): string {
  return uri.endsWith("/") ? uri : `${uri}/`;
}

async function mergeDirectory(
  fs: MigrationFs,
  fromDir: string,
  toDir: string,
): Promise<{ moved: number; failed: number }> {
  let moved = 0;
  let failed = 0;
  let entries: string[];
  try {
    entries = await fs.list(fromDir);
  } catch {
    return { moved, failed: failed + 1 };
  }
  for (const name of entries) {
    const from = `${fromDir}${name}`;
    const to = `${toDir}${name}`;
    try {
      const [src, dst] = await Promise.all([fs.exists(from), fs.exists(to)]);
      if (!dst.exists) {
        await fs.move(from, to);
        moved += 1;
      } else if (src.isDirectory && dst.isDirectory) {
        const inner = await mergeDirectory(fs, withSlash(from), withSlash(to));
        moved += inner.moved;
        failed += inner.failed;
      }
      // Same file in both places: the Menivor copy is newer, keep it; the
      // legacy one is removed with its folder below.
    } catch {
      failed += 1;
    }
  }
  return { moved, failed };
}

/**
 * Move `<documents>/reelforge/` to `<documents>/menivor/`. Idempotent: a second
 * run finds nothing to migrate. Never throws; on partial failure the legacy
 * folder is left in place so fallback reads still find the unmoved files.
 */
export async function migrateLegacyFolder(
  fs: MigrationFs,
  documentDirectory: string,
): Promise<MigrationResult> {
  const root = withSlash(documentDirectory);
  const legacy = `${root}${LEGACY_LOCAL_FOLDER}/`;
  const current = `${root}${LOCAL_FOLDER}/`;
  try {
    const legacyInfo = await fs.exists(legacy);
    if (!legacyInfo.exists || !legacyInfo.isDirectory) {
      return { outcome: "nothing-to-migrate", moved: 0, failed: 0 };
    }
    const currentInfo = await fs.exists(current);
    if (!currentInfo.exists) {
      await fs.move(legacy, current);
      return { outcome: "moved", moved: 1, failed: 0 };
    }
    const { moved, failed } = await mergeDirectory(fs, legacy, current);
    if (failed === 0) {
      await fs.remove(legacy);
      return { outcome: "merged", moved, failed };
    }
    return { outcome: "partial", moved, failed };
  } catch {
    return { outcome: "partial", moved: 0, failed: 1 };
  }
}

/**
 * Candidate locations to read a file from, newest first: the Menivor folder,
 * then the legacy folder (for anything the migration could not move).
 * `relativePath` is relative to the app folder, e.g. "exports/x.json".
 */
export function readCandidates(documentDirectory: string, relativePath: string): string[] {
  const root = withSlash(documentDirectory);
  return [
    `${root}${LOCAL_FOLDER}/${relativePath}`,
    `${root}${LEGACY_LOCAL_FOLDER}/${relativePath}`,
  ];
}

/**
 * Map a URI saved before the migration (inside `reelforge/`) to where the file
 * lives now (inside `menivor/`). Other URIs are returned unchanged.
 */
export function migratedUri(documentDirectory: string, uri: string): string {
  const root = withSlash(documentDirectory);
  const legacyPrefix = `${root}${LEGACY_LOCAL_FOLDER}/`;
  return uri.startsWith(legacyPrefix)
    ? `${root}${LOCAL_FOLDER}/${uri.slice(legacyPrefix.length)}`
    : uri;
}
