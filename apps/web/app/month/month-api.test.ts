import { beforeEach, describe, expect, it, vi } from "vitest";

const createJob = vi.fn();
const apiRequest = vi.fn();

vi.mock("@/lib/api", () => ({ createJob: (...a: unknown[]) => createJob(...a) }));
vi.mock("@/src/shared/api", () => ({ apiRequest: (...a: unknown[]) => apiRequest(...a) }));

import { decideIdea, makeReel, renderCarousel } from "@/components/month/api";
import type { MonthIdea } from "@/components/month/types";

const idea = {
  id: "idea1",
  kind: "reel",
  reel_job: { body: { params: { video_script: "Hi." } }, idempotency_key: "month-idea1" },
} as unknown as MonthIdea;

describe("content month api", () => {
  beforeEach(() => {
    createJob.mockReset();
    apiRequest.mockReset();
  });

  it("creates the reel with the per-idea idempotency key, then links the job", async () => {
    createJob.mockResolvedValue({ job_id: "job9" });
    apiRequest.mockResolvedValue({ idea: { id: "idea1" }, counts: {} });
    await makeReel(idea, { token: "t" });
    expect(createJob).toHaveBeenCalledWith(idea.reel_job!.body, { token: "t", idempotencyKey: "month-idea1" });
    expect(apiRequest).toHaveBeenCalledWith("/month/ideas/idea1/job", {
      method: "POST",
      body: { job_id: "job9" },
      options: { token: "t" },
    });
  });

  it("refuses to make a reel from a carousel", async () => {
    await expect(makeReel({ ...idea, reel_job: undefined } as MonthIdea)).rejects.toThrow("not a reel");
    expect(createJob).not.toHaveBeenCalled();
  });

  it("posts swipe decisions and renders with a size", async () => {
    apiRequest.mockResolvedValue({});
    await decideIdea("a b", "kept");
    expect(apiRequest).toHaveBeenCalledWith("/month/ideas/a%20b/decision", expect.objectContaining({ body: { decision: "kept" } }));
    await renderCarousel("x", "instagram");
    expect(apiRequest).toHaveBeenLastCalledWith("/month/ideas/x/render", expect.objectContaining({ body: { size: "instagram", video: true } }));
  });
});
