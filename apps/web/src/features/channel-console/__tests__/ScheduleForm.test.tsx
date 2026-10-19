import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ScheduleForm } from "../ScheduleForm";
import type { Channel } from "../api";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: async () => "test-token" }),
}));

const launchMock = vi.hoisted(() => ({
  state: {
    status: "ready",
    gate: {
      phase: "public",
      staffOverride: false,
      publishing: { open: true, reason: "" } as { open: boolean; reason: string },
      checkout: { open: true, reason: "" },
    },
  },
}));
vi.mock("@/src/shared/launch-gate/use-launch-gate", () => ({ useLaunchGate: () => launchMock.state }));


function envelope(data: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "OK",
    headers: { get: () => null },
    // Hoist `message` to the envelope top level so ApiError picks it up on errors.
    text: async () =>
      JSON.stringify({ status, data, message: (data as { message?: string })?.message }),
  } as unknown as Response;
}

const CHANNELS: Channel[] = [
  {
    provider: "tiktok",
    external_account_id: "acme",
    connected: true,
    status: "connected",
    scopes: "",
  },
];

describe("ScheduleForm", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    launchMock.state.gate.publishing = { open: true, reason: "" };
    cleanup();
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("POSTs /jobs/{id}/schedule with the form values + idempotency key", async () => {
    fetchMock.mockResolvedValueOnce(
      envelope({
        id: "s1",
        job_id: "job_1",
        platforms: ["tiktok"],
        scheduled_at: "x",
        status: "pending",
      }),
    );
    const onScheduled = vi.fn();

    render(<ScheduleForm channels={CHANNELS} onScheduled={onScheduled} />);

    fireEvent.change(screen.getByLabelText("Job ID"), { target: { value: "job_1" } });
    fireEvent.change(screen.getByLabelText("Publish at"), {
      target: { value: "2026-06-01T10:00" },
    });
    fireEvent.click(screen.getByRole("button", { name: /schedule/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain("/jobs/job_1/schedule");
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body as string);
    expect(body.platforms).toEqual(["tiktok"]);
    expect(typeof body.scheduled_at).toBe("string");
    expect(init.headers["Idempotency-Key"]).toBeTruthy();

    await waitFor(() => expect(onScheduled).toHaveBeenCalled());
    expect(await screen.findByText(/Scheduled for tiktok/)).toBeInTheDocument();
  });

  it("shows an error and does not call back when the API rejects", async () => {
    fetchMock.mockResolvedValueOnce(envelope({ message: "job not complete" }, 409));
    const onScheduled = vi.fn();

    render(<ScheduleForm channels={CHANNELS} onScheduled={onScheduled} />);

    fireEvent.change(screen.getByLabelText("Job ID"), { target: { value: "job_1" } });
    fireEvent.change(screen.getByLabelText("Publish at"), {
      target: { value: "2026-06-01T10:00" },
    });
    fireEvent.click(screen.getByRole("button", { name: /schedule/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/job not complete/i);
    expect(onScheduled).not.toHaveBeenCalled();
  });

  it("explains a closed publishing gate up front and never submits", async () => {
    launchMock.state.gate.publishing = {
      open: false,
      reason: "Posting to social platforms opens at public launch.",
    };
    render(<ScheduleForm channels={CHANNELS} onScheduled={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Job ID"), { target: { value: "job_1" } });
    fireEvent.change(screen.getByLabelText("Publish at"), {
      target: { value: "2026-06-01T10:00" },
    });
    expect(screen.getByRole("status")).toHaveTextContent(/opens at public launch/i);
    const button = screen.getByRole("button", { name: /schedule/i });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
