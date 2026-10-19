import { describe, expect, it } from "vitest";
import { SSO_SETTINGS_HREF, withoutHiddenSso } from "@/lib/sso-availability";
import { APP_NAV_GROUPS } from "@/components/app-shell/nav-items";

const links = [{ href: "/settings/team" }, { href: SSO_SETTINGS_HREF }];

describe("SSO availability (MN7a)", () => {
  it("drops the SSO link while SSO is off", () => {
    expect(withoutHiddenSso(links, false)).toEqual([{ href: "/settings/team" }]);
  });

  it("keeps it when SSO is on", () => {
    expect(withoutHiddenSso(links, true)).toEqual(links);
  });

  it("the app navigation has no SSO entry by default", () => {
    const hrefs = APP_NAV_GROUPS.flatMap((g) => g.items.map((i) => i.href));
    expect(hrefs).not.toContain(SSO_SETTINGS_HREF);
    expect(hrefs).toContain("/settings/team");
  });
});
