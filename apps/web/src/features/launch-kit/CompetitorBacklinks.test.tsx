import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const getApiToken = async () => "tok";
const findCompetitorBacklinks = vi.fn();

vi.mock("@/lib/use-api-token", () => ({ useApiToken: () => getApiToken }));
vi.mock("./api", async (orig) => {
  const actual = await orig<typeof import("./api")>();
  return { ...actual, findCompetitorBacklinks: (...a: unknown[]) => findCompetitorBacklinks(...a) };
});

import { CompetitorBacklinks } from "./CompetitorBacklinks";

describe("CompetitorBacklinks", () => {
  beforeEach(() => {
    findCompetitorBacklinks.mockReset();
  });

  it("shows an honest 'connect DataForSEO' state instead of a fake empty result", async () => {
    findCompetitorBacklinks.mockResolvedValue({
      domain: "competitor.com", live: false, configured: false, backlinks: [],
      fallback_directories: [{ id: "product_hunt", name: "Product Hunt", url: "https://producthunt.com/posts/new" }],
      message: "Competitor backlink data needs a DataForSEO account...",
    });
    render(<CompetitorBacklinks />);

    fireEvent.change(screen.getByLabelText("Competitor domain"), { target: { value: "competitor.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Look up" }));

    expect(await screen.findByTestId("backlinks-not-configured")).toBeTruthy();
    expect(screen.getByText("Connect DataForSEO for live backlink data")).toBeTruthy();
    expect(screen.getByText("Product Hunt")).toBeTruthy();
    expect(findCompetitorBacklinks).toHaveBeenCalledWith("competitor.com", false, { token: "tok" });
  });

  it("offers an explicit opt-in to spend credits when a key is configured but not yet fetched live", async () => {
    findCompetitorBacklinks.mockResolvedValue({
      domain: "competitor.com", live: false, configured: true, backlinks: [], fallback_directories: [],
      message: "A key is configured but allow_live was not set, so no credits were spent.",
    });
    render(<CompetitorBacklinks />);
    fireEvent.change(screen.getByLabelText("Competitor domain"), { target: { value: "competitor.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Look up" }));

    expect(await screen.findByTestId("backlinks-configured-not-live")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Fetch live data/ })).toBeTruthy();
  });

  it("shows real rows when live data comes back, and an honest zero-results message", async () => {
    findCompetitorBacklinks.mockResolvedValue({
      domain: "competitor.com", live: true, configured: true,
      backlinks: [{ source_domain: "blog.example.com", target_url: "https://blog.example.com/post", anchor: "", rank: 42 }],
      fallback_directories: [], message: "1 live backlink(s) from DataForSEO.",
    });
    render(<CompetitorBacklinks />);
    fireEvent.change(screen.getByLabelText("Competitor domain"), { target: { value: "competitor.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Look up" }));

    expect(await screen.findByTestId("backlinks-live")).toBeTruthy();
    expect(screen.getByText("blog.example.com")).toBeTruthy();
    expect(screen.getByText("rank 42")).toBeTruthy();
  });

  it("the look-up button stays disabled until the input looks like a domain", () => {
    render(<CompetitorBacklinks />);
    expect(screen.getByRole("button", { name: "Look up" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Competitor domain"), { target: { value: "not a domain" } });
    expect(screen.getByRole("button", { name: "Look up" })).toBeDisabled();
  });
});
