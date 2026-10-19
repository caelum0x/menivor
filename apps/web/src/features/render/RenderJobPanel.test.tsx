import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { RenderJobPanel } from "./RenderJobPanel";

const mocks = vi.hoisted(() => ({
  advanceRender: vi.fn(),
  getRender: vi.fn(),
  getToken: vi.fn(async () => "test-token"),
  startRender: vi.fn(),
}));

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: mocks.getToken }) }));
vi.mock("@/src/shared/api", () => ({ ApiError: class ApiError extends Error {} }));
vi.mock("./api", () => ({
  advanceRender: mocks.advanceRender,
  cancelRender: vi.fn(),
  getRender: mocks.getRender,
  listRenders: vi.fn(async () => ({ jobs: [], total: 0, hasMore: false })),
  playableOutputs: (job: { output_refs: string[]; output_urls?: string[] }) =>
    job.output_urls ?? job.output_refs.filter((ref) => /^https?:\/\//i.test(ref)),
  startRender: mocks.startRender,
}));

const queued = {
  id: "render-1",
  backend: "runpod",
  state: "IN_QUEUE",
  progress: 0,
  provider_ref: "provider-1",
  output_refs: [],
  cost_micros: 0,
  error: "",
};

beforeEach(() => {
  mocks.advanceRender.mockReset();
  mocks.getRender.mockReset();
  mocks.getToken.mockClear();
  mocks.startRender.mockReset();
  vi.stubGlobal("crypto", { randomUUID: vi.fn(() => `uuid-${Math.random()}`) });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("RenderJobPanel", () => {
  it("reuses the exact wallet-metered start key after an unknown failure", async () => {
    mocks.startRender.mockRejectedValue(new Error("unknown outcome"));
    render(<RenderJobPanel />);
    fireEvent.change(screen.getByPlaceholderText("Prompt"), { target: { value: "a launch" } });

    fireEvent.click(screen.getByRole("button", { name: /start render/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("unknown outcome");
    fireEvent.click(screen.getByRole("button", { name: /start render/i }));
    await waitFor(() => expect(mocks.startRender).toHaveBeenCalledTimes(2));

    expect(mocks.startRender.mock.calls[0]?.[1]?.idempotencyKey).toBeTruthy();
    expect(mocks.startRender.mock.calls[1]?.[1]?.idempotencyKey).toBe(
      mocks.startRender.mock.calls[0]?.[1]?.idempotencyKey,
    );
  });

  it("polls the accepted job to terminal through owner-scoped GET", async () => {
    vi.useFakeTimers();
    mocks.startRender.mockResolvedValue(queued);
    mocks.getRender.mockResolvedValue({
      ...queued,
      state: "COMPLETED",
      progress: 1,
      output_refs: ["renders/final.mp4"],
      cost_micros: 90000,
    });
    render(<RenderJobPanel />);
    fireEvent.change(screen.getByPlaceholderText("Prompt"), { target: { value: "a launch" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /start render/i }));
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText("Queued")).toBeInTheDocument();

    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(mocks.getRender).toHaveBeenCalledWith(
      "render-1",
      expect.objectContaining({ token: "test-token", signal: expect.any(AbortSignal) }),
    );
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.getByText(/not available for download yet/)).toBeInTheDocument();
  });
});
