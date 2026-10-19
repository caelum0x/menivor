import { afterEach, describe, expect, it, vi } from "vitest";

import {
  BROLL_LIBRARY_DEFAULT_LIMIT,
  BROLL_LIBRARY_MAX_LIMIT,
  getBrollClip,
  listBrollClips,
  listBrollPresets,
} from "./api";

function jsonResponse(
  body: unknown,
  init: { ok?: boolean; status?: number } = {},
): Response {
  const ok = init.ok ?? true;
  return {
    ok,
    status: init.status ?? (ok ? 200 : 400),
    statusText: ok ? "OK" : "Error",
    text: async () => JSON.stringify(body),
    headers: { get: () => null },
  } as unknown as Response;
}

function mockFetch() {
  const fn = vi.fn();
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("listBrollClips", () => {
  it("GETs /generation/broll/generations with the default limit", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: 200,
        data: [
          {
            generation_id: "gen_1",
            state: 1,
            progress: 100,
            broll_key: "results/gen_1.mp4",
            result_url: "https://cdn/gen_1.mp4",
            duration: 5,
          },
        ],
      }),
    );

    const res = await listBrollClips({}, { token: "tok" });

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain(
      `/generation/broll/generations?limit=${BROLL_LIBRARY_DEFAULT_LIMIT}`,
    );
    expect(init.method ?? "GET").toBe("GET");
    expect(init.headers["x-api-key"]).toBe("tok");
    expect(res).toHaveLength(1);
    expect(res[0]!.generation_id).toBe("gen_1");
  });

  it("clamps an over-large limit to the backend maximum", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(jsonResponse({ status: 200, data: [] }));

    await listBrollClips({ limit: 9999 }, { token: "tok" });

    const [url] = fetchMock.mock.calls[0]!;
    expect(url).toContain(
      `/generation/broll/generations?limit=${BROLL_LIBRARY_MAX_LIMIT}`,
    );
  });

  it("normalizes a wrapped { generations: [] } payload", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: 200,
        data: {
          generations: [
            { generation_id: "gen_2", state: 4, progress: 40, broll_key: "" },
          ],
        },
      }),
    );

    const res = await listBrollClips({}, { token: "tok" });

    expect(res).toHaveLength(1);
    expect(res[0]!.generation_id).toBe("gen_2");
  });
});

describe("getBrollClip", () => {
  it("GETs /generation/broll/generations/{id} url-encoding the id", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: 200,
        data: {
          generation_id: "gen a/b",
          state: 4,
          progress: 25,
          broll_key: "",
        },
      }),
    );

    const res = await getBrollClip("gen a/b", { token: "tok" });

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/generation/broll/generations/gen%20a%2Fb");
    expect(init.method ?? "GET").toBe("GET");
    expect(res.progress).toBe(25);
  });
});

describe("listBrollPresets", () => {
  it("GETs /generation/broll/presets and returns a bare array", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: 200,
        data: [
          {
            id: "p1",
            name: "Slow zoom",
            description: "",
            mode: "t2v",
            prompt_template: "",
            thumbnail_url: "",
            workflow_id: "",
            default_params: {},
          },
        ],
      }),
    );

    const res = await listBrollPresets({ token: "tok" });

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/generation/broll/presets");
    expect(init.method ?? "GET").toBe("GET");
    expect(res[0]!.id).toBe("p1");
  });

  it("normalizes a wrapped { presets: [] } payload", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: 200,
        data: { presets: [{ id: "p2", name: "Pan", mode: "i2v" }] },
      }),
    );

    const res = await listBrollPresets({ token: "tok" });

    expect(res).toHaveLength(1);
    expect(res[0]!.id).toBe("p2");
  });
});
