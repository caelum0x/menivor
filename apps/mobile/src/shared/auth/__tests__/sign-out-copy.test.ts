import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { signOutPrompt } from "../sign-out-copy";

describe("sign-out prompt", () => {
  it("store builds never talk about guest/device accounts or internal screens", () => {
    for (const linked of [true, false]) {
      const prompt = signOutPrompt({ linked, lab: false });
      expect(prompt.offerLink).toBe(false);
      expect(`${prompt.title} ${prompt.message}`).not.toMatch(/device account|guest|Account Access/i);
      expect(prompt.title).toBe("Sign out?");
    }
  });

  it("a linked account gets the plain prompt in every build", () => {
    expect(signOutPrompt({ linked: true, lab: true }).offerLink).toBe(false);
  });

  it("lab sessions keep the device-account warning for unlinked test accounts", () => {
    const prompt = signOutPrompt({ linked: false, lab: true });
    expect(prompt.offerLink).toBe(true);
    expect(prompt.message).toMatch(/device account/i);
  });

  it("useConfirmSignOut takes its wording from signOutPrompt", () => {
    const hook = fs.readFileSync(path.join(__dirname, "../useConfirmSignOut.ts"), "utf8");
    expect(hook).toContain("signOutPrompt(");
    expect(hook).not.toContain("GUEST_WARNING =");
  });
});
