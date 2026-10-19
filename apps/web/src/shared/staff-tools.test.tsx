import { describe, expect, it, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";

import {
  APP_NAV_GROUPS,
  PRIMARY_NAV_ITEMS,
  STAFF_TOOL_ROUTES,
  isStaffToolRoute,
  staffToolsGated,
} from "@/components/app-shell/nav-items";

const replace = vi.fn();
let pathname = "/hook-lab";
let staffStatus = "denied";

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
  useRouter: () => ({ replace }),
}));
vi.mock("@/components/admin/use-is-staff", () => ({
  useIsStaff: () => ({ status: staffStatus, errorMessage: "" }),
}));

import { StaffToolGuard } from "@/components/app-shell/StaffToolGuard";

describe("WP3.2 staff-only tools", () => {
  beforeEach(() => {
    replace.mockReset();
  });

  it("keeps every primary destination and its sub-pages public", () => {
    for (const item of PRIMARY_NAV_ITEMS) {
      expect(isStaffToolRoute(item.href)).toBe(false);
      for (const m of item.match) expect(isStaffToolRoute(m)).toBe(false);
    }
    for (const path of ["/create/advanced", "/new", "/editor", "/wallet/plans", "/spend", "/usage", "/workspace"]) {
      expect(isStaffToolRoute(path)).toBe(false);
    }
  });

  it("hides the lab and studio tools, keeping the winners page public", () => {
    for (const path of ["/hook-lab", "/film", "/studio/design/abc", "/insights", "/reels/calendar"]) {
      expect(isStaffToolRoute(path)).toBe(true);
    }
    expect(isStaffToolRoute("/insights/winners")).toBe(false);
    expect(isStaffToolRoute("/filmography")).toBe(false);
    expect(STAFF_TOOL_ROUTES.length).toBeGreaterThanOrEqual(30);
  });

  it("keeps the full tool map in the tree for staff", () => {
    const hrefs = APP_NAV_GROUPS.flatMap((g) => g.items.map((i) => i.href));
    expect(hrefs.length).toBeGreaterThan(40); // nothing was removed from the tree
  });

  it("the gate is on by default and `open` turns it off", () => {
    expect(staffToolsGated(undefined)).toBe(true);
    expect(staffToolsGated("open")).toBe(false);
  });

  it("sends a non-staff user on a hidden page to Home", () => {
    pathname = "/hook-lab";
    staffStatus = "denied";
    render(<StaffToolGuard />);
    expect(replace).toHaveBeenCalledWith("/reels");
  });

  it("leaves staff, checking users and public pages alone", () => {
    pathname = "/hook-lab";
    staffStatus = "staff";
    render(<StaffToolGuard />);
    staffStatus = "checking";
    render(<StaffToolGuard />);
    pathname = "/create";
    staffStatus = "denied";
    render(<StaffToolGuard />);
    expect(replace).not.toHaveBeenCalled();
  });
});
