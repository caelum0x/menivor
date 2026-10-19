import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { TimelineEditor } from "./TimelineEditor";

const mocks = vi.hoisted(() => ({
  createTimelineExport: vi.fn(),
  getToken: vi.fn(async () => "test-token"),
}));

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: mocks.getToken }),
}));

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  createTimelineExport: mocks.createTimelineExport,
}));

vi.mock("./use-editor-job", () => ({
  useEditorJob: (jobId: string) =>
    jobId
      ? {
          status: "ready",
          error: "",
          job: {
            job_id: jobId,
            state: 1,
            progress: 100,
            result_url: "https://media.example/export.mp4",
          },
        }
      : { status: "idle", error: "", job: null },
}));

beforeEach(() => {
  mocks.createTimelineExport.mockReset();
  mocks.getToken.mockClear();
  vi.stubGlobal("crypto", { randomUUID: vi.fn(() => `uuid-${Math.random()}`) });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("TimelineEditor", () => {
  it("reuses an idempotency key for an exact failed retry and rotates after edits", async () => {
    mocks.createTimelineExport.mockRejectedValue(new Error("temporary failure"));
    render(<TimelineEditor sourceJobId="source-1" sourceDuration={10} />);

    fireEvent.click(screen.getByRole("button", { name: /export timeline/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("temporary failure");
    fireEvent.click(screen.getByRole("button", { name: /export timeline/i }));
    await waitFor(() => expect(mocks.createTimelineExport).toHaveBeenCalledTimes(2));

    const firstKey = mocks.createTimelineExport.mock.calls[0]?.[2]?.idempotencyKey;
    const retryKey = mocks.createTimelineExport.mock.calls[1]?.[2]?.idempotencyKey;
    expect(firstKey).toBeTruthy();
    expect(retryKey).toBe(firstKey);

    fireEvent.change(screen.getByPlaceholderText(/caption for this clip/i), {
      target: { value: "Changed command" },
    });
    fireEvent.click(screen.getByRole("button", { name: /export timeline/i }));
    await waitFor(() => expect(mocks.createTimelineExport).toHaveBeenCalledTimes(3));
    expect(mocks.createTimelineExport.mock.calls[2]?.[2]?.idempotencyKey).not.toBe(firstKey);
  });

  it("prevents concurrent duplicate submission and surfaces the accepted job", async () => {
    let accept: ((value: { job_id: string }) => void) | undefined;
    mocks.createTimelineExport.mockImplementation(
      () => new Promise((resolve) => { accept = resolve; }),
    );
    render(<TimelineEditor sourceJobId="source-1" sourceDuration={10} />);

    const button = screen.getByRole("button", { name: /export timeline/i });
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => expect(mocks.createTimelineExport).toHaveBeenCalledTimes(1));
    accept?.({ job_id: "export-123456789" });

    expect(await screen.findByRole("link", { name: /download timeline export/i })).toHaveAttribute(
      "href",
      "https://media.example/export.mp4",
    );
    expect(screen.getByRole("link", { name: /open export job/i })).toHaveAttribute(
      "href",
      "/jobs/export-123456789",
    );
  });

  it("discards the previous source EDL when the source job changes", async () => {
    mocks.createTimelineExport.mockResolvedValue({ job_id: "export-2" });
    const view = render(<TimelineEditor sourceJobId="source-1" sourceDuration={10} />);
    fireEvent.click(screen.getByRole("button", { name: /^clip$/i }));
    expect(screen.getByText(/2 clips/i)).toBeInTheDocument();

    view.rerender(
      <TimelineEditor
        sourceJobId="source-2"
        sourceDuration={5}
        initialIn={1}
        initialOut={4}
      />,
    );
    await waitFor(() => expect(screen.getByText(/1 clip/i)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /export timeline/i }));
    await waitFor(() => expect(mocks.createTimelineExport).toHaveBeenCalledOnce());
    expect(mocks.createTimelineExport.mock.calls[0]?.[0]).toBe("source-2");
    expect(mocks.createTimelineExport.mock.calls[0]?.[1]?.segments).toEqual([
      { source_in: 1, source_out: 4, speed: 1, caption: null },
    ]);
  });

  it("ignores an accepted response from a source that has since changed", async () => {
    let accept: ((value: { job_id: string }) => void) | undefined;
    mocks.createTimelineExport.mockImplementation(
      () => new Promise((resolve) => { accept = resolve; }),
    );
    const onExported = vi.fn();
    const view = render(
      <TimelineEditor
        sourceJobId="source-1"
        sourceDuration={10}
        onExported={onExported}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /export timeline/i }));
    await waitFor(() => expect(mocks.createTimelineExport).toHaveBeenCalledOnce());

    view.rerender(
      <TimelineEditor
        sourceJobId="source-2"
        sourceDuration={5}
        onExported={onExported}
      />,
    );
    accept?.({ job_id: "stale-export" });

    await waitFor(() => expect(screen.getByText(/1 clip/i)).toBeInTheDocument());
    expect(onExported).not.toHaveBeenCalled();
    expect(screen.queryByRole("link", { name: /open export job/i })).not.toBeInTheDocument();
  });
});
