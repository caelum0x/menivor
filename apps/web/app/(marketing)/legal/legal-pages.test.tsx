/**
 * M7.3: the subprocessor list, the data-requests page (export and delete path,
 * KVKK note) and the privacy policy links between them.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import PrivacyPolicyPage from "../privacy/page";
import DataRequestsPage from "./data-requests/page";
import { EXPORT_LINK_MINUTES, RESPONSE_DAYS, VERBIS_STATUS } from "./data-requests/constants";
import SubprocessorsPage from "./subprocessors/page";
import { SUBPROCESSORS } from "./subprocessors/subprocessors";

const API_ROOT = path.resolve(__dirname, "../../../../api");

describe("subprocessors", () => {
  it("every entry names its purpose, data, timing, location and https terms link", () => {
    const names = SUBPROCESSORS.map((s) => s.name);
    expect(new Set(names).size).toBe(names.length);
    for (const sp of SUBPROCESSORS) {
      expect(sp.purpose.length).toBeGreaterThan(10);
      expect(sp.data.length).toBeGreaterThan(5);
      expect(sp.when.length).toBeGreaterThan(3);
      expect(sp.location.length).toBeGreaterThan(3);
      expect(sp.termsUrl).toMatch(/^https:\/\/[^\s]+$/);
    }
  });

  it("lists the providers the API calls in production", () => {
    const expected = ["Oracle Cloud Infrastructure", "Cloudflare", "Clerk", "Anthropic", "Dodo Payments", "ElevenLabs"];
    expect(SUBPROCESSORS.map((s) => s.name)).toEqual(expect.arrayContaining(expected));
  });

  it("renders one table row per subprocessor with its terms link", () => {
    render(<SubprocessorsPage />);
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(SUBPROCESSORS.length + 1);
    const link = within(table).getAllByRole("link")[0] as HTMLAnchorElement;
    expect(link.href).toBe(SUBPROCESSORS[0]!.termsUrl);
  });
});

describe("data requests", () => {
  it("states the export link lifetime the API actually uses", () => {
    const src = fs.readFileSync(path.join(API_ROOT, "app/services/compliance/export.py"), "utf8");
    const seconds = Number(/^EXPORT_URL_EXPIRES: int = (\d+)/m.exec(src)?.[1]);
    expect(EXPORT_LINK_MINUTES * 60).toBe(seconds);
  });

  it("documents export, delete, KVKK and the VERBİS status", () => {
    const { container } = render(<DataRequestsPage />);
    for (const id of ["export", "delete", "other-rights", "kvkk", "eu"]) {
      expect(container.querySelector(`section#${id}`)).not.toBeNull();
    }
    expect(screen.getAllByRole("link", { name: /settings, privacy/i })[0]!.getAttribute("href")).toBe("/settings/privacy");
    expect(container.textContent).toContain(VERBIS_STATUS);
    expect(container.textContent).toContain(`within ${RESPONSE_DAYS} days`);
    expect(container.textContent).toContain("Article 11");
  });
});

describe("privacy policy", () => {
  it("links to the subprocessor list, the data requests page and the KVKK note", () => {
    const { container } = render(<PrivacyPolicyPage />);
    const hrefs = Array.from(container.querySelectorAll("a")).map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(
      expect.arrayContaining(["/legal/subprocessors", "/legal/data-requests", "/legal/data-requests#kvkk", "/legal/content-credentials"]),
    );
  });
});
