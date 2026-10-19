import { beforeEach, describe, expect, it } from "vitest";

import {
  deleteDraft,
  listDrafts,
  saveDraft,
  type DraftStorage,
} from "../drafts";

/** In-memory AsyncStorage stand-in for pure Node tests. */
function memoryStorage(seed: Record<string, string> = {}): DraftStorage & {
  dump: () => Record<string, string>;
} {
  const map = new Map<string, string>(Object.entries(seed));
  return {
    getItem: (key) => Promise.resolve(map.get(key) ?? null),
    setItem: (key, value) => {
      map.set(key, value);
      return Promise.resolve();
    },
    removeItem: (key) => {
      map.delete(key);
      return Promise.resolve();
    },
    dump: () => Object.fromEntries(map),
  };
}

describe("reel drafts persistence", () => {
  let storage: ReturnType<typeof memoryStorage>;

  beforeEach(() => {
    storage = memoryStorage();
  });

  it("returns an empty list when nothing is stored", async () => {
    expect(await listDrafts(storage)).toEqual([]);
  });

  it("saves and lists a draft round-trip", async () => {
    const saved = await saveDraft(
      {
        subject: "Ship log #1",
        media: {
          uri: "file:///clip.mp4",
          name: "clip.mp4",
          mimeType: "video/mp4",
          size: 1024,
        },
        captionStyle: "hormozi",
      },
      storage,
    );

    const listed = await listDrafts(storage);
    expect(listed).toHaveLength(1);
    expect(listed[0].id).toBe(saved.id);
    expect(listed[0].subject).toBe("Ship log #1");
    expect(listed[0].media?.uri).toBe("file:///clip.mp4");
    expect(listed[0].captionStyle).toBe("hormozi");
    expect(typeof listed[0].createdAt).toBe("number");
  });

  it("orders drafts newest first", async () => {
    const first = await saveDraft({ subject: "first" }, storage);
    // Force a distinct, later timestamp for the second draft.
    await new Promise((resolve) => setTimeout(resolve, 2));
    const second = await saveDraft({ subject: "second" }, storage);

    const listed = await listDrafts(storage);
    expect(listed.map((d) => d.id)).toEqual([second.id, first.id]);
  });

  it("deletes a draft by id and leaves the rest", async () => {
    const a = await saveDraft({ subject: "keep" }, storage);
    const b = await saveDraft({ subject: "remove" }, storage);

    const remaining = await deleteDraft(b.id, storage);
    expect(remaining.map((d) => d.id)).toEqual([a.id]);
    expect((await listDrafts(storage)).map((d) => d.id)).toEqual([a.id]);
  });

  it("treats deleting a missing id as a no-op", async () => {
    const a = await saveDraft({ subject: "keep" }, storage);
    const remaining = await deleteDraft("does-not-exist", storage);
    expect(remaining.map((d) => d.id)).toEqual([a.id]);
  });

  it("recovers from a corrupt payload as an empty list", async () => {
    const corrupt = memoryStorage({ "menivor.reelDrafts.v1": "{not json" });
    expect(await listDrafts(corrupt)).toEqual([]);
  });

  it("drops malformed entries but keeps well-formed ones", async () => {
    const mixed = memoryStorage({
      "menivor.reelDrafts.v1": JSON.stringify([
        { id: "ok", subject: "fine", createdAt: 5 },
        { id: "", subject: "bad-id", createdAt: 6 },
        { subject: "no-id", createdAt: 7 },
        "garbage",
      ]),
    });
    const listed = await listDrafts(mixed);
    expect(listed.map((d) => d.id)).toEqual(["ok"]);
  });
});
