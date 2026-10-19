import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";

const jobState = { value: 4 };
const getJob = vi.fn(async (id: string) => ({
  job_id: id,
  state: jobState.value,
  progress: 10,
  stages: {},
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, getJob: (id: string) => getJob(id), retryJob: vi.fn() };
});
const getToken = async () => "token";
vi.mock("@/lib/use-api-token", () => ({ useApiToken: () => getToken }));
vi.mock("@/src/features/plans", () => ({ PlanUpsell: () => null }));
vi.mock("@/src/features/paywall-moment", () => ({ PaywallMoment: () => null }));
vi.mock("@/src/shared/access", () => ({ BuyCredits: () => null }));
vi.mock("./ResultHero", () => ({ ResultHero: () => null }));

import { POLL_INTERVAL_MS } from "@/lib/api";
import {
  FAST_POLL_WINDOW_MS,
  MAX_POLL_DELAY_MS,
  VariantResults,
  nextPollDelay,
} from "./VariantResults";

const JOB_A = "a".repeat(32);
const JOB_B = "b".repeat(32);

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("nextPollDelay", () => {
  it("polls at the normal pace for 20 minutes, then backs off to a minute", () => {
    expect(nextPollDelay(0, POLL_INTERVAL_MS)).toBe(POLL_INTERVAL_MS);
    expect(nextPollDelay(FAST_POLL_WINDOW_MS - 1, POLL_INTERVAL_MS)).toBe(POLL_INTERVAL_MS);
    const first = nextPollDelay(FAST_POLL_WINDOW_MS, POLL_INTERVAL_MS);
    expect(first).toBeGreaterThan(POLL_INTERVAL_MS);
    let delay = first;
    for (let i = 0; i < 20; i += 1) delay = nextPollDelay(FAST_POLL_WINDOW_MS + i * 60_000, delay);
    expect(delay).toBe(MAX_POLL_DELAY_MS);
  });
});

describe("VariantResults polling", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: false });
    jobState.value = 4; // processing
    getJob.mockClear();
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("keeps polling past 20 minutes and stops once every reel is finished", async () => {
    render(<VariantResults jobIds={[JOB_A, JOB_B]} />);
    await advance(0);
    expect(getJob).toHaveBeenCalled();

    await advance(FAST_POLL_WINDOW_MS + 5 * 60_000);
    const callsAfter25Min = getJob.mock.calls.length;
    expect(screen.getByRole("status")).toHaveTextContent("we email you when your reels");

    await advance(3 * 60_000);
    expect(getJob.mock.calls.length).toBeGreaterThan(callsAfter25Min);

    jobState.value = 1; // complete
    await advance(MAX_POLL_DELAY_MS);
    const callsAtFinish = getJob.mock.calls.length;
    await advance(10 * 60_000);
    expect(getJob.mock.calls.length).toBe(callsAtFinish);
    expect(screen.queryByRole("status")).toBeNull();
  });
});
