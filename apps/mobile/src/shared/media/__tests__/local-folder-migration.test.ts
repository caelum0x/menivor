import { describe, expect, it } from "vitest";

import {
  migrateLegacyFolder,
  migratedUri,
  readCandidates,
  type MigrationFs,
} from "../local-folder-migration";

const DOCS = "file:///docs/";

/** In-memory tree: directories end with "/", files do not. */
function memoryFs(paths: string[], failMoves: string[] = []) {
  const entries = new Set(paths);
  const isDir = (p: string) => p.endsWith("/");
  const fs: MigrationFs = {
    async exists(uri) {
      const dir = uri.endsWith("/") ? uri : `${uri}/`;
      if (entries.has(dir)) return { exists: true, isDirectory: true };
      return { exists: entries.has(uri), isDirectory: false };
    },
    async list(dirUri) {
      const names = new Set<string>();
      for (const p of entries) {
        if (p !== dirUri && p.startsWith(dirUri)) {
          const rest = p.slice(dirUri.length);
          names.add(rest.split("/")[0]);
        }
      }
      return [...names];
    },
    async move(from, to) {
      if (failMoves.includes(from)) throw new Error("EPERM");
      const fromDir = entries.has(`${from.replace(/\/$/, "")}/`);
      const src = fromDir ? `${from.replace(/\/$/, "")}/` : from;
      const dst = fromDir ? `${to.replace(/\/$/, "")}/` : to;
      for (const p of [...entries]) {
        if (p === src || (isDir(src) && p.startsWith(src))) {
          entries.delete(p);
          entries.add(dst + p.slice(src.length));
        }
      }
    },
    async makeDir(uri) {
      entries.add(uri);
    },
    async remove(uri) {
      for (const p of [...entries]) if (p.startsWith(uri)) entries.delete(p);
    },
  };
  return { fs, entries };
}

describe("migrateLegacyFolder", () => {
  it("does nothing on a fresh install", async () => {
    const { fs } = memoryFs([]);
    expect((await migrateLegacyFolder(fs, DOCS)).outcome).toBe("nothing-to-migrate");
  });

  it("renames reelforge/ to menivor/ when menivor/ does not exist", async () => {
    const { fs, entries } = memoryFs([
      `${DOCS}reelforge/`,
      `${DOCS}reelforge/broll-history-1.json`,
      `${DOCS}reelforge/exports/`,
      `${DOCS}reelforge/exports/reelforge-j1.mp4`,
    ]);
    const result = await migrateLegacyFolder(fs, DOCS);
    expect(result.outcome).toBe("moved");
    expect(entries.has(`${DOCS}menivor/broll-history-1.json`)).toBe(true);
    expect(entries.has(`${DOCS}menivor/exports/reelforge-j1.mp4`)).toBe(true);
    expect([...entries].some((p) => p.includes("/reelforge/"))).toBe(false);
    // Idempotent.
    expect((await migrateLegacyFolder(fs, DOCS)).outcome).toBe("nothing-to-migrate");
  });

  it("merges into an existing menivor/ without overwriting newer files", async () => {
    const { fs, entries } = memoryFs([
      `${DOCS}reelforge/`,
      `${DOCS}reelforge/a.json`,
      `${DOCS}reelforge/b.json`,
      `${DOCS}reelforge/exports/`,
      `${DOCS}reelforge/exports/old.mp4`,
      `${DOCS}menivor/`,
      `${DOCS}menivor/a.json`,
      `${DOCS}menivor/exports/`,
    ]);
    const result = await migrateLegacyFolder(fs, DOCS);
    expect(result.outcome).toBe("merged");
    expect(entries.has(`${DOCS}menivor/b.json`)).toBe(true);
    expect(entries.has(`${DOCS}menivor/exports/old.mp4`)).toBe(true);
    expect(entries.has(`${DOCS}reelforge/`)).toBe(false);
  });

  it("keeps the legacy folder when a move fails so fallback reads still work", async () => {
    const { fs, entries } = memoryFs(
      [`${DOCS}reelforge/`, `${DOCS}reelforge/a.json`, `${DOCS}menivor/`],
      [`${DOCS}reelforge/a.json`],
    );
    const result = await migrateLegacyFolder(fs, DOCS);
    expect(result.outcome).toBe("partial");
    expect(entries.has(`${DOCS}reelforge/a.json`)).toBe(true);
  });
});

describe("read fallbacks", () => {
  it("prefers menivor/ then reelforge/", () => {
    expect(readCandidates(DOCS, "exports/x.json")).toEqual([
      `${DOCS}menivor/exports/x.json`,
      `${DOCS}reelforge/exports/x.json`,
    ]);
  });

  it("remaps pre-migration URIs only", () => {
    expect(migratedUri(DOCS, `${DOCS}reelforge/exports/r.mp4`)).toBe(
      `${DOCS}menivor/exports/r.mp4`,
    );
    expect(migratedUri(DOCS, "https://cdn.example.com/r.mp4")).toBe(
      "https://cdn.example.com/r.mp4",
    );
  });
});
