import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { LaunchPlatform, LaunchPlatformsOverview } from "./api";

const getApiToken = async () => "tok";
const listLaunchPlatforms = vi.fn();
const setPlatformStatus = vi.fn();

vi.mock("@/lib/use-api-token", () => ({ useApiToken: () => getApiToken }));
vi.mock("./api", async (orig) => {
  const actual = await orig<typeof import("./api")>();
  return {
    ...actual,
    listLaunchPlatforms: (...a: unknown[]) => listLaunchPlatforms(...a),
    setPlatformStatus: (...a: unknown[]) => setPlatformStatus(...a),
  };
});

import { PlatformChecklist } from "./PlatformChecklist";

const platform = (over: Partial<LaunchPlatform>): LaunchPlatform => ({
  id: "product_hunt", name: "Product Hunt", url: "https://producthunt.com/posts/new",
  categories: ["saas", "ai"], note: "Biggest general launch audience.", status: "not_started",
  submitted_at: null, tracking_note: "",
  ...over,
});

const overview = (platforms: readonly LaunchPlatform[]): LaunchPlatformsOverview => ({
  platforms, category: "", product_name: "",
});

describe("PlatformChecklist", () => {
  beforeEach(() => {
    listLaunchPlatforms.mockReset();
    setPlatformStatus.mockReset();
  });

  it("lists platforms with their status and a progress count", async () => {
    listLaunchPlatforms.mockResolvedValue(overview([platform({}), platform({ id: "devhunt", name: "DevHunt", status: "live" })]));
    render(<PlatformChecklist productName="Menivor" />);
    expect(await screen.findByText("Product Hunt")).toBeTruthy();
    expect(screen.getByText("DevHunt")).toBeTruthy();
    expect(screen.getByTestId("platform-progress").textContent).toBe("1 / 2 submitted or live");
  });

  it("clicking a status pill advances it and saves via the API", async () => {
    listLaunchPlatforms.mockResolvedValue(overview([platform({})]));
    setPlatformStatus.mockResolvedValue(platform({ status: "submitted" }));
    render(<PlatformChecklist productName="Menivor" />);
    await screen.findByText("Product Hunt");

    fireEvent.click(screen.getByRole("button", { name: /Product Hunt status: Not started/ }));

    expect(await screen.findByText("Submitted")).toBeTruthy();
    expect(setPlatformStatus).toHaveBeenCalledWith(
      { productName: "Menivor", platformId: "product_hunt", status: "submitted" },
      { token: "tok" },
    );
  });

  it("filtering by category narrows the list", async () => {
    listLaunchPlatforms.mockResolvedValue(
      overview([platform({ id: "a", name: "Alpha", categories: ["ai"] }), platform({ id: "b", name: "Beta", categories: ["oss"] })]),
    );
    render(<PlatformChecklist productName="Menivor" />);
    await screen.findByText("Alpha");

    fireEvent.change(screen.getByLabelText("Filter by category"), { target: { value: "oss" } });
    expect(screen.queryByText("Alpha")).toBeNull();
    expect(screen.getByText("Beta")).toBeTruthy();
  });

  it("refuses to save a status change without a product name", async () => {
    listLaunchPlatforms.mockResolvedValue(overview([platform({})]));
    render(<PlatformChecklist productName="" />);
    await screen.findByText("Product Hunt");

    fireEvent.click(screen.getByRole("button", { name: /Product Hunt status: Not started/ }));

    expect(setPlatformStatus).not.toHaveBeenCalled();
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter a product name");
  });
});
