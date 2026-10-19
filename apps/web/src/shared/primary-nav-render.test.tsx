import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

let staffStatus = "denied";

vi.mock("next/navigation", () => ({
  usePathname: () => "/reels",
  useRouter: () => ({ replace: vi.fn() }),
}));
vi.mock("@/components/admin/use-is-staff", () => ({
  useIsStaff: () => ({ status: staffStatus, errorMessage: "" }),
}));

import { PrimaryNavBar } from "@/components/app-shell/PrimaryNav";

describe("WP3.2 primary nav", () => {
  it("renders exactly five items for a non-staff user", () => {
    staffStatus = "denied";
    render(<PrimaryNavBar />);
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(nav.querySelectorAll("li")).toHaveLength(5);
    expect(screen.queryByRole("button", { name: "More" })).toBeNull();
  });

  it("adds More for staff", () => {
    staffStatus = "staff";
    render(<PrimaryNavBar />);
    expect(screen.getAllByRole("button", { name: "More" }).length).toBeGreaterThan(0);
  });
});
