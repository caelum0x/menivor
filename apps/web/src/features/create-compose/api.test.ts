import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  compileBodyFrom,
  compileReel,
  getJob,
  isJobFailed,
  isJobTerminal,
  jobAssetUrl,
  pollCompileJob,
  previewSlotVideo,
  type JobSnapshot,
} from "./api";
import type { InstantiateResult } from "@/src/features/templates/api";

/** Minimal `Response` stand-in matching what `apiRequest` reads. */
function jsonResponse(data: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    statusText: ok ? "OK" : "Error",
    headers: { get: () => null },
    text: async () => JSON.stringify({ status, data }),
  } as unknown as Response;
}

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("compileReel", () => {
  it("POSTs the pipeline-ready reel draft to /jobs and returns the job id", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ job_id: "job_123", state: 4, progress: 0 }));

    // The body is the `JobCreateRequest`-shaped reel_draft, POSTed to the real
    // canonical create endpoint (`POST /jobs`), not a fictional `/reels/compile`.
    const body = {
      video_subject: "s",
      video_script: "",
      layout: "split",
      caption_style: "karaoke",
      camera_motion: "none",
    };
    const result = await compileReel(body, { token: "tok" });

    expect(result).toEqual({ job_id: "job_123", state: 4, progress: 0 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(String(url)).toMatch(/\/jobs$/);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual(body);
    expect(init.headers["x-api-key"]).toBe("tok");
  });
});

describe("getJob", () => {
  it("GETs /jobs/{id} url-encoding the id", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ job_id: "a/b", status: "processing" }),
    );

    await getJob("a/b", { token: "tok" });

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(String(url)).toMatch(/\/jobs\/a%2Fb$/);
    expect(init.method ?? "GET").toBe("GET");
  });
});

describe("job status helpers", () => {
  it("treats numeric state 1/-1 as terminal and -1 as failed", () => {
    expect(isJobTerminal({ job_id: "j", state: 1 })).toBe(true);
    expect(isJobTerminal({ job_id: "j", state: -1 })).toBe(true);
    expect(isJobTerminal({ job_id: "j", state: 4 })).toBe(false);
    expect(isJobFailed({ job_id: "j", state: -1 })).toBe(true);
    expect(isJobFailed({ job_id: "j", state: 1 })).toBe(false);
  });

  it("falls back to the product status string", () => {
    expect(isJobTerminal({ job_id: "j", status: "completed" })).toBe(true);
    expect(isJobTerminal({ job_id: "j", status: "queued" })).toBe(false);
    expect(isJobFailed({ job_id: "j", status: "failed" })).toBe(true);
  });

  it("prefers asset_url then result_url", () => {
    expect(jobAssetUrl({ job_id: "j", asset_url: "a", result_url: "r" })).toBe(
      "a",
    );
    expect(jobAssetUrl({ job_id: "j", result_url: "r" })).toBe("r");
    expect(jobAssetUrl({ job_id: "j" })).toBeUndefined();
  });
});

describe("compileBodyFrom", () => {
  it("extracts the pipeline-ready reel_draft to POST to /jobs", () => {
    const inst: InstantiateResult = {
      template: "t",
      version: "1",
      render_spec: { fps: 24 },
      reel_draft: {
        video_subject: "hi",
        video_script: "",
        layout: "split",
        caption_style: "karaoke",
        camera_motion: "none",
      },
    };
    const body = compileBodyFrom(inst);
    expect(body).toEqual(inst.reel_draft);
  });
});

describe("pollCompileJob", () => {
  it("polls /jobs/{id} until the job is terminal", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ job_id: "j", state: 4 }))
      .mockResolvedValueOnce(jsonResponse({ job_id: "j", state: 4 }))
      .mockResolvedValueOnce(
        jsonResponse({ job_id: "j", state: 1, result_url: "done.mp4" }),
      );

    const ticks: JobSnapshot[] = [];
    const res = await pollCompileJob("j", {
      intervalMs: 1,
      onTick: (job) => ticks.push(job),
    });

    expect(res.timedOut).toBe(false);
    expect(res.value.state).toBe(1);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(ticks).toHaveLength(3);
  });

  it("returns timedOut when the deadline elapses first", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ job_id: "j", state: 4 }));

    const res = await pollCompileJob("j", { intervalMs: 5, maxMs: 0 });

    expect(res.timedOut).toBe(true);
    expect(res.value.state).toBe(4);
  });
});

describe("previewSlotVideo", () => {
  it("POSTs the prompt to /media/videos", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ asset_url: "clip.mp4" }));

    const res = await previewSlotVideo({ prompt: "a cat" }, { token: "t" });

    expect(res.asset_url).toBe("clip.mp4");
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(String(url)).toMatch(/\/media\/videos$/);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ prompt: "a cat" });
  });
});
