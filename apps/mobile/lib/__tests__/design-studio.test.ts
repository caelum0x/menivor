import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  MAX_TEXT_CHARS,
  canvasChanged,
  createDesign,
  designMediaSource,
  exportIsCurrent,
  generateDesigns,
  listDesigns,
  openableExports,
  orderOptions,
  previewScale,
  saveDesign,
  templatesForSize,
  textLayers,
  validatePrompt,
  webEditorUrl,
  withLayerText,
  type Canvas,
  type GeneratedOption,
  type TemplateInfo,
} from "@/lib/design-studio";

type FetchMock = ReturnType<typeof vi.fn>;
let fetchMock: FetchMock;

function respond(data: unknown, status = 200): void {
  fetchMock.mockResolvedValueOnce({
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(status < 300 ? { status, data } : { status, message: data }),
    headers: { get: () => null },
  });
}

function lastCall(): { url: string; init: RequestInit } {
  const [url, init] = fetchMock.mock.calls[fetchMock.mock.calls.length - 1] as [string, RequestInit];
  return { url, init };
}

const CANVAS: Canvas = {
  version: 1,
  pages: [
    {
      background: "#ffffff",
      layers: [
        {
          id: "h",
          type: "text",
          name: "Headline",
          x: 0,
          y: 0,
          width: 100,
          height: 40,
          rotation: 0,
          opacity: 1,
          props: { text: "Hello", fontFamily: "Inter", fontSize: 48, fontWeight: 700, color: "#111111", align: "left", lineHeight: 1.1 },
        },
        {
          id: "bg",
          type: "rect",
          name: "Band",
          x: 0,
          y: 0,
          width: 10,
          height: 10,
          rotation: 0,
          opacity: 1,
          props: { fill: "#000000", stroke: "", strokeWidth: 0 },
        },
        {
          id: "hid",
          type: "text",
          name: "Hidden",
          x: 0,
          y: 0,
          width: 10,
          height: 10,
          rotation: 0,
          opacity: 1,
          hidden: true,
          props: { text: "x", fontFamily: "Inter", fontSize: 12, fontWeight: 400, color: "#111111", align: "left", lineHeight: 1 },
        },
      ],
    },
    { background: "#000000", layers: [] },
  ],
};

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("design studio client", () => {
  it("generates with the LLM copy writer on and the caller's key", async () => {
    respond({ options: [], size_preset: "square", width: 1080, height: 1080 });
    await generateDesigns({ prompt: "Launch", size_preset: "square", brand_kit_id: null }, { token: "k" });
    const { url, init } = lastCall();
    expect(url).toMatch(/\/design\/generate$/);
    expect(JSON.parse(String(init.body))).toEqual({
      prompt: "Launch",
      size_preset: "square",
      brand_kit_id: null,
      use_llm: true,
    });
    expect((init.headers as Record<string, string>)["x-api-key"]).toBe("k");
  });

  it("creates, lists and saves designs on the right routes", async () => {
    respond({ id: "d1" });
    await createDesign({ size_preset: "square", canvas: CANVAS, template: "bold" });
    expect(lastCall().init.method).toBe("POST");
    expect(lastCall().url).toMatch(/\/design\/docs$/);

    respond({ designs: [], total: 0 });
    await listDesigns(undefined, 999);
    expect(lastCall().url).toMatch(/\/design\/docs\?limit=100&offset=0$/);

    respond({ id: "d1" });
    await saveDesign("d 1", { title: "T" });
    expect(lastCall().init.method).toBe("PATCH");
    expect(lastCall().url).toMatch(/\/design\/docs\/d%201$/);
  });
});

describe("design studio helpers", () => {
  it("builds authenticated media sources and web editor links", () => {
    const src = designMediaSource("uploads/a b.png", "k");
    expect(src.uri).toMatch(/\/design\/media\?key=uploads%2Fa%20b\.png$/);
    expect(src.headers).toEqual({ "x-api-key": "k" });
    expect(designMediaSource("uploads/a.png", undefined).headers).toBeUndefined();
    expect(webEditorUrl("abc", "https://example.com/")).toBe("https://example.com/studio/design/abc");
  });

  it("filters templates by size", () => {
    const templates: TemplateInfo[] = [
      { id: null, slug: "a", name: "A", description: "", presets: ["square"], builtin: true },
      { id: null, slug: "b", name: "B", description: "", presets: ["story"], builtin: true },
      { id: null, slug: "c", name: "C", description: "", presets: [], builtin: true },
    ];
    expect(templatesForSize(templates, "square").map((t) => t.slug)).toEqual(["a", "c"]);
  });

  it("validates prompts", () => {
    expect(validatePrompt("  a  ")).toMatchObject({ ok: false });
    expect(validatePrompt("  launch   day ")).toEqual({ ok: true, prompt: "launch day" });
  });

  it("puts the picked template first", () => {
    const opts = ["a", "b", "c"].map((t) => ({ template: t, name: t, description: "", canvas: CANVAS })) as GeneratedOption[];
    expect(orderOptions(opts, "b").map((o) => o.template)).toEqual(["b", "a", "c"]);
    expect(orderOptions(opts, "").map((o) => o.template)).toEqual(["a", "b", "c"]);
  });

  it("edits text layers immutably", () => {
    expect(textLayers(CANVAS).map((r) => r.layer.id)).toEqual(["h"]);
    const next = withLayerText(CANVAS, 0, "h", "Hi there");
    const layer = next.pages[0]?.layers[0];
    expect(layer?.type === "text" && layer.props.text).toBe("Hi there");
    const original = CANVAS.pages[0]?.layers[0];
    expect(original?.type === "text" && original.props.text).toBe("Hello");
    expect(next.pages[1]).toBe(CANVAS.pages[1]);
    expect(canvasChanged(CANVAS, next)).toBe(true);
    expect(canvasChanged(CANVAS, withLayerText(CANVAS, 0, "bg", "nope"))).toBe(false);
    const long = withLayerText(CANVAS, 0, "h", "x".repeat(MAX_TEXT_CHARS + 50));
    const clipped = long.pages[0]?.layers[0];
    expect(clipped?.type === "text" && clipped.props.text.length).toBe(MAX_TEXT_CHARS);
  });

  it("knows when exports are openable and current", () => {
    const doc = {
      exports: [
        { key: "uploads/1.png", url: "https://r2/1" },
        { key: "uploads/2.png", url: null },
      ],
      exported_at: "2026-09-25T10:00:00Z",
      updated_at: "2026-09-25T10:00:00.500Z",
    };
    expect(openableExports(doc)).toEqual([{ page: 1, url: "https://r2/1" }]);
    expect(exportIsCurrent(doc)).toBe(true);
    expect(exportIsCurrent({ ...doc, updated_at: "2026-09-25T11:00:00Z" })).toBe(false);
    expect(exportIsCurrent({ ...doc, exported_at: null })).toBe(false);
  });

  it("scales previews to fit", () => {
    expect(previewScale(1080, 1920, 360)).toBeCloseTo(1 / 3);
    expect(previewScale(1080, 1920, 360, 320)).toBeCloseTo(320 / 1920);
    expect(previewScale(0, 10, 100)).toBe(0);
  });
});
