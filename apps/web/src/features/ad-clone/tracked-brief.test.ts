import { afterEach, describe, expect, it } from "vitest";

import { TRACKED_BRIEF_KEY, takeTrackedBrief } from "./AdCloneWizard";

afterEach(() => {
  window.sessionStorage.clear();
  window.history.replaceState(null, "", "/");
});

describe("tracked brief hand-off", () => {
  it("reads the competitor tracker brief once, only with from=tracked", () => {
    window.sessionStorage.setItem(TRACKED_BRIEF_KEY, JSON.stringify({ brief: { version: 1 }, source_url: "https://x" }));
    expect(takeTrackedBrief()).toBeNull();
    window.history.replaceState(null, "", "/ad-clone?from=tracked");
    expect(takeTrackedBrief()).toEqual({ version: 1 });
    expect(window.sessionStorage.getItem(TRACKED_BRIEF_KEY)).toBeNull();
    expect(takeTrackedBrief()).toBeNull();
  });
});
