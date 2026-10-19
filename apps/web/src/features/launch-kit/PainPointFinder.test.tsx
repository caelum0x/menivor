import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { PainPointDraft } from "./api";

const getApiToken = async () => "tok";
const listPainPointDrafts = vi.fn();
const searchPainPoints = vi.fn();
const setPainPointDraftStatus = vi.fn();

vi.mock("@/lib/use-api-token", () => ({ useApiToken: () => getApiToken }));
vi.mock("./api", async (orig) => {
  const actual = await orig<typeof import("./api")>();
  return {
    ...actual,
    listPainPointDrafts: (...a: unknown[]) => listPainPointDrafts(...a),
    searchPainPoints: (...a: unknown[]) => searchPainPoints(...a),
    setPainPointDraftStatus: (...a: unknown[]) => setPainPointDraftStatus(...a),
  };
});

import { PainPointFinder } from "./PainPointFinder";

const draft = (over: Partial<PainPointDraft>): PainPointDraft => ({
  id: "d1", product_name: "Menivor", query: "onboarding", subreddit: "saas",
  thread_url: "https://reddit.com/r/saas/comments/abc", thread_title: "Onboarding drop-off",
  snippet: "", upvotes: 10, age_days: 2, draft_reply: "Ran into this too...", status: "drafted",
  created_at: "2026-10-15T00:00:00Z",
  ...over,
});

describe("PainPointFinder", () => {
  beforeEach(() => {
    listPainPointDrafts.mockReset().mockResolvedValue({ drafts: [] });
    searchPainPoints.mockReset();
    setPainPointDraftStatus.mockReset();
  });

  it("shows an empty state and never offers a post button", async () => {
    render(<PainPointFinder productName="Menivor" />);
    expect(await screen.findByText("No drafts yet. Search above to find threads.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /post/i })).toBeNull();
  });

  it("searching calls the API, shows the note, and refreshes drafts", async () => {
    searchPainPoints.mockResolvedValue({
      query: "onboarding", threads: [], count: 1,
      note: "Drafts only. Review and post these yourself -- nothing here posts to Reddit.",
    });
    listPainPointDrafts.mockResolvedValueOnce({ drafts: [] }).mockResolvedValueOnce({ drafts: [draft({})] });
    render(<PainPointFinder productName="Menivor" />);
    await screen.findByText("No drafts yet. Search above to find threads.");

    fireEvent.change(screen.getByLabelText("Search query"), { target: { value: "onboarding" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByText("Onboarding drop-off")).toBeTruthy();
    expect(screen.getByText(/nothing here posts to Reddit/)).toBeTruthy();
    expect(searchPainPoints).toHaveBeenCalledWith(
      { query: "onboarding", subreddits: [], productName: "Menivor" },
      { token: "tok" },
    );
  });

  it("parses comma-separated subreddits, stripping an r/ prefix", async () => {
    searchPainPoints.mockResolvedValue({ query: "q", threads: [], count: 0, note: "" });
    render(<PainPointFinder productName="Menivor" />);
    await screen.findByText("No drafts yet. Search above to find threads.");

    fireEvent.change(screen.getByLabelText("Search query"), { target: { value: "q" } });
    fireEvent.change(screen.getByLabelText("Subreddits (optional, comma-separated)"), {
      target: { value: "r/saas, indiehackers" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    await screen.findByText("No drafts yet. Search above to find threads.");
    expect(searchPainPoints).toHaveBeenCalledWith(
      { query: "q", subreddits: ["saas", "indiehackers"], productName: "Menivor" },
      { token: "tok" },
    );
  });

  it("approving a draft calls the API and updates its badge", async () => {
    listPainPointDrafts.mockResolvedValue({ drafts: [draft({})] });
    setPainPointDraftStatus.mockResolvedValue(draft({ status: "approved" }));
    render(<PainPointFinder productName="Menivor" />);
    await screen.findByText("Onboarding drop-off");

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    expect(await screen.findByText("Approved")).toBeTruthy();
    expect(setPainPointDraftStatus).toHaveBeenCalledWith("d1", "approved", { token: "tok" });
  });

  it("dismissing a draft calls the API and updates its badge", async () => {
    listPainPointDrafts.mockResolvedValue({ drafts: [draft({})] });
    setPainPointDraftStatus.mockResolvedValue(draft({ status: "dismissed" }));
    render(<PainPointFinder productName="Menivor" />);
    await screen.findByText("Onboarding drop-off");

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));

    expect(await screen.findByText("Dismissed")).toBeTruthy();
    expect(setPainPointDraftStatus).toHaveBeenCalledWith("d1", "dismissed", { token: "tok" });
  });
});
