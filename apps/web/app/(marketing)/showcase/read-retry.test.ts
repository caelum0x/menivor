import { describe, expect, it, vi } from "vitest";

import { withReadRetry } from "@/src/shared/api/client";

const res = (status: number) => new Response("{}", { status });

describe("withReadRetry (showcase and every GET during an API restart)", () => {
  it("retries network errors and edge 502s, then returns the good response", async () => {
    const run = vi
      .fn<() => Promise<Response>>()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(res(502))
      .mockResolvedValueOnce(res(200));
    const out = await withReadRetry(run, [0, 0]);
    expect(out.status).toBe(200);
    expect(run).toHaveBeenCalledTimes(3);
  });

  it("does not retry client errors or app 503s and gives up after the last delay", async () => {
    for (const status of [404, 503]) {
      const once = vi.fn<() => Promise<Response>>().mockResolvedValue(res(status));
      expect((await withReadRetry(once, [0, 0])).status).toBe(status);
      expect(once).toHaveBeenCalledTimes(1);
    }
    const down = vi.fn<() => Promise<Response>>().mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(withReadRetry(down, [0, 0])).rejects.toThrow("Failed to fetch");
    expect(down).toHaveBeenCalledTimes(3);
  });

  it("never retries an aborted request", async () => {
    const aborted = vi.fn<() => Promise<Response>>().mockRejectedValue(new DOMException("x", "AbortError"));
    await expect(withReadRetry(aborted, [0, 0])).rejects.toThrow();
    expect(aborted).toHaveBeenCalledTimes(1);
  });
});
