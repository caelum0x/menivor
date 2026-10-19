import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { ApprovalItemCard } from "./ApprovalItemCard";
import type { ApprovalItem } from "./api";

const mocks = vi.hoisted(() => ({ decideApproval: vi.fn() }));

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "test-token" }) }));
vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  decideApproval: mocks.decideApproval,
}));
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a>,
}));

function item(source: ApprovalItem["source"]): ApprovalItem {
  return {
    id: "item-1",
    source,
    external_ref: "ref-1",
    title: "Held post for tiktok",
    summary: "",
    risk: "medium",
    payload: {},
    edited_payload: null,
    status: "pending",
    decided_by: null,
    decided_via: "",
    decided_at: null,
    decision_note: "",
    result: {},
    error: "",
    expires_at: null,
    created_at: null,
    updated_at: null,
    open_url: null,
    can_decide: true,
  };
}

const CLOSED = { open: false, reason: "Posting to social platforms opens at public launch." };

afterEach(() => {
  cleanup();
  mocks.decideApproval.mockReset();
});

describe("ApprovalItemCard launch gate", () => {
  it("blocks approving a post-scheduling item while publishing is closed, but allows reject", () => {
    render(<ApprovalItemCard item={item("publish_hold")} onDecided={vi.fn()} publishGate={CLOSED} />);
    expect(screen.getByRole("status")).toHaveTextContent(/opens at public launch/i);
    expect(screen.getByRole("button", { name: /^approve$/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^reject$/i })).toBeEnabled();
  });

  it("does not gate items that never post (ad budget)", () => {
    render(<ApprovalItemCard item={item("ad_budget")} onDecided={vi.fn()} publishGate={CLOSED} />);
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByRole("button", { name: /^approve$/i })).toBeEnabled();
  });

  it("shows a server refusal without the request id", async () => {
    mocks.decideApproval.mockRejectedValue(
      Object.assign(
        new Error("0123456789abcdef0123456789abcdef: this post is no longer held"),
        { status: 409 },
      ),
    );
    render(<ApprovalItemCard item={item("publish_hold")} onDecided={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /^approve$/i }));
    expect(await screen.findByText("This post is no longer held")).toBeInTheDocument();
  });
});
