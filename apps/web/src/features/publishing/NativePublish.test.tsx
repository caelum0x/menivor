import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { buildNativePublishCommand, NativePublish } from "./NativePublish";

const mocks = vi.hoisted(() => ({
  getToken: vi.fn(async () => "test-token"),
  listNativePlatforms: vi.fn(),
  publishNative: vi.fn(),
  schedulePost: vi.fn(),
  launch: {
    status: "ready",
    gate: {
      phase: "public",
      staffOverride: false,
      publishing: { open: true, reason: "" },
      checkout: { open: true, reason: "" },
    },
  },
}));

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: mocks.getToken }) }));
vi.mock("@/src/shared/api", () => ({ ApiError: class ApiError extends Error {} }));
vi.mock("./api", () => ({
  listNativePlatforms: mocks.listNativePlatforms,
  publishNative: mocks.publishNative,
}));
vi.mock("@/src/features/channel-console/api", () => ({ schedulePost: mocks.schedulePost }));
vi.mock("@/src/features/reels-library/components/ReelPicker", () => ({ ReelPicker: () => null }));
vi.mock("@/src/shared/launch-gate/use-launch-gate", () => ({ useLaunchGate: () => mocks.launch }));

beforeEach(() => {
  mocks.getToken.mockClear();
  mocks.listNativePlatforms.mockReset().mockResolvedValue({ platforms: ["youtube", "tiktok"] });
  mocks.publishNative.mockReset();
  mocks.schedulePost.mockReset();
  vi.stubGlobal("crypto", { randomUUID: vi.fn(() => `uuid-${Math.random()}`) });
  mocks.launch.gate.publishing = { open: true, reason: "" };
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("native publishing command", () => {
  it("normalizes immediate metadata and enforces backend collection bounds", () => {
    expect(
      buildNativePublishCommand({
        jobId: " job-1 ",
        platform: " youtube ",
        title: " Launch ",
        caption: " Watch now ",
        hashtags: "viral, fyp, viral, reels",
        publishAt: "",
      }),
    ).toEqual({
      kind: "publish",
      jobId: "job-1",
      body: {
        platform: "youtube",
        title: "Launch",
        caption: "Watch now",
        hashtags: ["viral", "fyp", "reels"],
      },
    });
    expect(() =>
      buildNativePublishCommand({
        jobId: "job-1",
        platform: "youtube",
        title: "",
        caption: "",
        hashtags: Array.from({ length: 31 }, (_, index) => `tag${index}`).join(","),
        publishAt: "",
      }),
    ).toThrow(/at most 30/i);
  });

  it("rejects invalid and past schedules before network I/O", async () => {
    render(<NativePublish />);
    await screen.findByRole("option", { name: "youtube" });
    fireEvent.change(screen.getByLabelText(/job id/i), { target: { value: "job-1" } });
    fireEvent.change(screen.getByLabelText(/schedule for later/i), {
      target: { value: "2020-01-01T12:00" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^schedule$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/must be in the future/i);
    expect(mocks.schedulePost).not.toHaveBeenCalled();
    expect(screen.getByText(/platform defaults/i)).toBeInTheDocument();
  });

  it("reuses an exact failed publish key and rotates it after an edit", async () => {
    mocks.publishNative.mockRejectedValue(new Error("unknown outcome"));
    render(<NativePublish />);
    await screen.findByRole("option", { name: "youtube" });
    fireEvent.change(screen.getByLabelText(/job id/i), { target: { value: "job-1" } });

    fireEvent.click(screen.getByRole("button", { name: /^publish$/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/unknown outcome/i);
    fireEvent.click(screen.getByRole("button", { name: /^publish$/i }));
    await waitFor(() => expect(mocks.publishNative).toHaveBeenCalledTimes(2));
    const firstKey = mocks.publishNative.mock.calls[0]?.[2]?.idempotencyKey;
    expect(mocks.publishNative.mock.calls[1]?.[2]?.idempotencyKey).toBe(firstKey);

    fireEvent.change(screen.getByLabelText(/^caption$/i), { target: { value: "new copy" } });
    fireEvent.click(screen.getByRole("button", { name: /^publish$/i }));
    await waitFor(() => expect(mocks.publishNative).toHaveBeenCalledTimes(3));
    expect(mocks.publishNative.mock.calls[2]?.[2]?.idempotencyKey).not.toBe(firstKey);
  });

  it("is single-flight and submits one normalized future schedule", async () => {
    let accept: ((value: object) => void) | undefined;
    mocks.schedulePost.mockImplementation(() => new Promise((resolve) => { accept = resolve; }));
    render(<NativePublish />);
    await screen.findByRole("option", { name: "youtube" });
    fireEvent.change(screen.getByLabelText(/job id/i), { target: { value: " job-1 " } });
    fireEvent.change(screen.getByLabelText(/schedule for later/i), {
      target: { value: "2099-01-01T12:00" },
    });
    const submit = screen.getByRole("button", { name: /^schedule$/i });
    fireEvent.click(submit);
    fireEvent.click(submit);
    await waitFor(() => expect(mocks.schedulePost).toHaveBeenCalledOnce());
    expect(mocks.schedulePost.mock.calls[0]?.[0]).toBe("job-1");
    expect(mocks.schedulePost.mock.calls[0]?.[1]?.platforms).toEqual(["youtube"]);
    expect(mocks.schedulePost.mock.calls[0]?.[1]?.scheduled_at).toMatch(/^2099-01-01T/);

    accept?.({ id: "schedule-1", job_id: "job-1", platforms: ["youtube"], status: "pending" });
    expect(await screen.findByText(/queued for youtube/i)).toBeInTheDocument();
  });

  it("shows the launch reason up front and keeps publish disabled when publishing is closed", async () => {
    mocks.launch.gate.publishing = {
      open: false,
      reason: "Posting to social platforms opens at public launch.",
    };
    render(<NativePublish />);
    await screen.findByRole("option", { name: "youtube" });
    fireEvent.change(screen.getByLabelText(/job id/i), { target: { value: "job-1" } });
    expect(screen.getByRole("status")).toHaveTextContent(/opens at public launch/i);
    const publish = screen.getByRole("button", { name: /^publish$/i });
    expect(publish).toBeDisabled();
    fireEvent.click(publish);
    expect(mocks.publishNative).not.toHaveBeenCalled();
  });

  it("maps a raw launch-gate refusal to readable copy", async () => {
    mocks.publishNative.mockRejectedValue(
      Object.assign(
        new Error("0123456789abcdef0123456789abcdef: direct publishing is not enabled for this launch phase"),
        { status: 403 },
      ),
    );
    render(<NativePublish />);
    await screen.findByRole("option", { name: "youtube" });
    fireEvent.change(screen.getByLabelText(/job id/i), { target: { value: "job-1" } });
    fireEvent.click(screen.getByRole("button", { name: /^publish$/i }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/private beta/i);
    expect(alert).not.toHaveTextContent("0123456789abcdef");
  });
});
