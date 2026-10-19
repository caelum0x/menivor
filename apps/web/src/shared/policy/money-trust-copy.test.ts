/**
 * P-A3 copy-lint for the Wave C money-and-trust surfaces (MN8, MN7a, MN5):
 * the developer webhooks page, the SSO contact-sales page and the content
 * report page. No error-level denylist hits and no emoji. (The integrations
 * page is left out: it has an older vendor-name hit outside these packages.)
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { checkUnits, type Denylist, type Surface } from "./copy-check";
import { sourceUnits } from "./source-units";

const WEB_ROOT = path.resolve(__dirname, "../../..");
const list = JSON.parse(
  fs.readFileSync(path.resolve(WEB_ROOT, "../../policy/copy-denylist.json"), "utf8"),
) as Denylist;

const FILES: readonly { readonly rel: string; readonly surface: Surface }[] = [
  { rel: "app/developer/page.tsx", surface: "app-ui" },
  { rel: "app/settings/sso/page.tsx", surface: "app-ui" },
  { rel: "lib/sso-availability.ts", surface: "app-ui" },
  { rel: "app/(marketing)/legal/report/page.tsx", surface: "legal" },
  { rel: "app/(marketing)/legal/report/ReportForm.tsx", surface: "legal" },
];

const EMOJI = /\p{Extended_Pictographic}/u;

describe("money and trust copy", () => {
  for (const { rel, surface } of FILES) {
    it(`${rel} passes the copy denylist and has no emoji`, () => {
      const code = fs.readFileSync(path.join(WEB_ROOT, rel), "utf8");
      const { units } = sourceUnits(code, rel, surface);
      const errors = checkUnits(list, units).filter((hit) => hit.severity === "error");
      expect(errors.map((h) => `${h.ruleId}: ${h.excerpt}`)).toEqual([]);
      expect(units.filter((u) => EMOJI.test(u.text)).map((u) => u.text)).toEqual([]);
    });
  }
});
