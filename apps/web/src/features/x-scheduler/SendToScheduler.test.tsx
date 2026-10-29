import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SendToScheduler } from "./SendToScheduler";

const mocks = vi.hoisted(() => ({
  listSchedulerConnections: vi.fn(),
  listSchedulerTargets: vi.fn(),
  scheduleSchedulerPost: vi.fn(),
}));

vi.mock("@/components/auth/clerk-safe", () => ({ useAuth: () => ({ getToken: async () => "token" }) }));
vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    listSchedulerConnections: mocks.listSchedulerConnections,
    listSchedulerTargets: mocks.listSchedulerTargets,
    scheduleSchedulerPost: mocks.scheduleSchedulerPost,
  };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("SendToScheduler", () => {
  it("counts characters toward the X limit and shows a provider quota error", async () => {
    mocks.listSchedulerConnections.mockResolvedValue([
      { provider: "buffer", connected: true, key_hint: "••••9f3a", created_at: null },
      { provider: "typefully", connected: false, key_hint: "", created_at: null },
    ]);
    mocks.listSchedulerTargets.mockResolvedValue([
      { id: "ch-x", name: "Ada", handle: "ada", organization: "Acme", service: "x", provider: "buffer" },
    ]);
    mocks.scheduleSchedulerPost.mockRejectedValue(
      new Error("Buffer's free plan allows 10 scheduled posts per channel, and this channel has reached that limit. Nothing was posted."),
    );

    render(<SendToScheduler source="render" sourceId="render-1" kind="video" />);
    fireEvent.click(screen.getByRole("button", { name: /send to buffer \/ typefully/i }));
    expect(await screen.findByText("0/280")).toBeInTheDocument();
    expect(await screen.findByRole("option", { name: /ada/i })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Caption"), { target: { value: "Launch day" } });
    expect(screen.getByText("10/280")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/10 scheduled posts per channel/);
    await waitFor(() => expect(mocks.scheduleSchedulerPost).toHaveBeenCalledWith(
      expect.objectContaining({ provider: "buffer", target_id: "ch-x", source: "render", source_id: "render-1", caption: "Launch day", when: "queue" }),
      expect.objectContaining({ token: "token" }),
    ));
    expect(screen.queryByText(/buf_live|api_key/i)).not.toBeInTheDocument();
  });
});
