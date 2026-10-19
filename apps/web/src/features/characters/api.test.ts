import { afterEach, describe, expect, it, vi } from "vitest";

import { deleteCharacter, getCharacter } from "./api";

/** Minimal Response-like object for the shared apiRequest transport. */
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

const CHARACTER = {
  id: "char-1",
  name: "Nova",
  descriptors: ["silver hair"],
  reference_images: [],
  style: "3D pixar",
  lora_ref: "",
  identity_key: "abc123def456",
};

describe("getCharacter", () => {
  it("calls GET /characters/{id} and returns the unwrapped character", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(jsonResponse({ status: 200, data: CHARACTER }));

    const char = await getCharacter("char-1", { token: "tok" });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/characters/char-1");
    expect(init.method).toBe("GET");
    expect(init.headers["x-api-key"]).toBe("tok");
    expect(char.name).toBe("Nova");
  });

  it("url-encodes the id path segment", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(jsonResponse({ status: 200, data: CHARACTER }));

    await getCharacter("a/b id", { token: "tok" });

    const [url] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/characters/a%2Fb%20id");
  });
});

describe("deleteCharacter", () => {
  it("sends DELETE /characters/{id} and returns the result", async () => {
    const fetchMock = mockFetch();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ status: 200, data: { deleted: true, id: "char-1" } }),
    );

    const res = await deleteCharacter("char-1", { token: "tok" });

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/characters/char-1");
    expect(init.method).toBe("DELETE");
    expect(res).toEqual({ deleted: true, id: "char-1" });
  });
});
