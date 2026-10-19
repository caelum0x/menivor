/**
 * The landing hero leads with the narrowest wedge the capture pipeline ships
 * end to end: paste an App Store (or Play Store) link, get a rendered
 * vertical demo back (see `app/domains/capture/sources.py` + `store.py` +
 * `slideshow.py` on the API, and `link-kind.ts` on the web, which already
 * classifies `apps.apple.com`/`itunes.apple.com` as `app_store`). This test
 * pins the hero copy to that wedge and to the live `OFFER` copy so the page
 * never claims a free reel the API flag is not actually granting.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import { describe, expect, it } from "vitest";

const HERO = fs.readFileSync(path.join(__dirname, "_components/OneFlowHero.tsx"), "utf8");
const INPUT = fs.readFileSync(path.join(__dirname, "_components/HeroLinkInput.tsx"), "utf8");

describe("landing hero: App Store -> TikTok demo wedge", () => {
  it("headline leads with pasting an App Store link into a demo video", () => {
    expect(HERO).toMatch(/Paste your App Store link/i);
    expect(HERO).toMatch(/TikTok-ready demo video/i);
  });

  it("still names Play Store, a site, and a screen recording as the same flow", () => {
    expect(HERO).toMatch(/Google Play link/i);
    expect(HERO).toMatch(/screen recording/i);
  });

  it("the free-reel line reads the live OFFER copy, not a hardcoded claim", () => {
    expect(HERO).toMatch(/import \{ OFFER \} from "@\/lib\/offer"/);
    expect(HERO).toMatch(/\{OFFER\.short\}/);
  });

  it("only shows the free-reel claim in public posture (never during waitlist/beta)", () => {
    expect(HERO).toMatch(/posture\.mode === "public" && \(\s*<p[^>]*>\{OFFER\.short\}/);
  });

  it("the paste box placeholder mentions an App Store link but still accepts any link", () => {
    expect(INPUT).toMatch(/App Store link/i);
    expect(INPUT).toMatch(/any other link|type a topic/i);
  });
});
