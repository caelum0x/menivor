import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { LaunchChecklist as LaunchChecklistData } from "./api";

const getApiToken = async () => "tok";
const getLaunchChecklist = vi.fn();
const markPlaybookStep = vi.fn();

vi.mock("@/lib/use-api-token", () => ({ useApiToken: () => getApiToken }));
vi.mock("./api", async (orig) => {
  const actual = await orig<typeof import("./api")>();
  return {
    ...actual,
    getLaunchChecklist: (...a: unknown[]) => getLaunchChecklist(...a),
    markPlaybookStep: (...a: unknown[]) => markPlaybookStep(...a),
  };
});

import { LaunchChecklist } from "./LaunchChecklist";

const checklist = (over: Partial<LaunchChecklistData> = {}): LaunchChecklistData => ({
  product_name: "Menivor", known_product: true, done: 1, total: 2, platforms_submitted: [],
  steps: [
    { key: "launch_everywhere", title: "Launch everywhere", detail: "List on every directory.", status: "done", note: "", updated_at: null },
    { key: "cold_outreach", title: "Network + cold outreach", detail: "Friends, ex-colleagues, LinkedIn.", status: "pending", note: "", updated_at: null },
  ],
  ...over,
});

describe("LaunchChecklist", () => {
  beforeEach(() => {
    getLaunchChecklist.mockReset();
    markPlaybookStep.mockReset();
  });

  it("without a product name, asks for one instead of calling the API", () => {
    render(<LaunchChecklist productName="" />);
    expect(screen.getByText("Enter a product name above to see its checklist.")).toBeTruthy();
    expect(getLaunchChecklist).not.toHaveBeenCalled();
  });

  it("shows steps with progress and a derived done step struck through", async () => {
    getLaunchChecklist.mockResolvedValue(checklist());
    render(<LaunchChecklist productName="Menivor" />);
    expect(await screen.findByText("Launch everywhere")).toBeTruthy();
    expect(screen.getByTestId("checklist-progress").textContent).toBe("1 / 2 steps done");
    expect(screen.getByText("Launch everywhere").className).toContain("line-through");
  });

  it("toggling a pending step marks it done", async () => {
    getLaunchChecklist.mockResolvedValueOnce(checklist()).mockResolvedValueOnce(
      checklist({ done: 2, steps: [
        { key: "launch_everywhere", title: "Launch everywhere", detail: "List on every directory.", status: "done", note: "", updated_at: null },
        { key: "cold_outreach", title: "Network + cold outreach", detail: "Friends, ex-colleagues, LinkedIn.", status: "done", note: "", updated_at: null },
      ] }),
    );
    markPlaybookStep.mockResolvedValue({ product_name: "Menivor", step_key: "cold_outreach", status: "done", note: "" });
    render(<LaunchChecklist productName="Menivor" />);
    await screen.findByText("Network + cold outreach");

    fireEvent.click(screen.getByRole("button", { name: "Network + cold outreach: pending" }));

    expect(await screen.findByTestId("checklist-progress")).toHaveTextContent("2 / 2 steps done");
    expect(markPlaybookStep).toHaveBeenCalledWith(
      { productName: "Menivor", stepKey: "cold_outreach", status: "done" },
      { token: "tok" },
    );
  });
});
