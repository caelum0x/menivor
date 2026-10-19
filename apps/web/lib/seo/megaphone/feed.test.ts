import { describe, expect, it, vi } from "vitest";
import { isoDuration, jsonLdText, loadFeed, parseFeed, parseVideo, productLink, videoObject, videoSitemapXml } from "./feed";

const good = {
  id: "bidstage-de-cpv45-2026w41",
  product: "bidstage",
  title: "636 new construction work tenders in Germany this week",
  description: "New tenders. Made with Menivor.",
  video_url: "https://media.menivor.com/megaphone/bidstage/bidstage-de-cpv45-2026w41.mp4",
  poster_url: "https://media.menivor.com/megaphone/bidstage/bidstage-de-cpv45-2026w41.jpg",
  duration_s: 31.4,
  width: 1080,
  height: 1920,
  upload_date: "2026-10-08T06:00:00Z",
  landing_url: "https://bidstage.app/tenders/de/cpv-45000000?utm_source=menivor&utm_medium=video",
  language: "en",
  transcript: "636 new public tenders </script><script>alert(1)</script>",
  dubs: [{ language: "es", video_url: "https://media.menivor.com/megaphone/bidstage/x.es.mp4" }, { language: "xx1", video_url: "https://evil.example/x.mp4" }],
};

describe("megaphone feed", () => {
  it("keeps a well-formed entry", () => {
    const v = parseVideo(good);
    expect(v?.product).toBe("bidstage");
    expect(v?.durationS).toBe(31.4);
    expect(v?.dubs).toEqual([{ language: "es", videoUrl: "https://media.menivor.com/megaphone/bidstage/x.es.mp4" }]);
  });

  it.each([
    ["foreign video host", { video_url: "https://evil.example/a.mp4" }],
    ["non-https landing", { landing_url: "http://bidstage.app/" }],
    ["unknown landing host", { landing_url: "https://evil.example/" }],
    ["unknown product", { product: "rally" }],
    ["bad id", { id: "../../x" }],
    ["bad duration", { duration_s: -1 }],
    ["bad date", { upload_date: "soon" }],
  ])("drops an entry with %s", (_label, patch) => {
    expect(parseVideo({ ...good, ...patch })).toBeNull();
  });

  it("parses a feed, dedupes ids and tolerates junk", () => {
    expect(parseFeed({ videos: [good, good, null, 7] })).toHaveLength(1);
    expect(parseFeed(null)).toEqual([]);
    expect(parseFeed({ videos: "nope" })).toEqual([]);
  });

  it("loadFeed degrades to [] on HTTP errors and exceptions", async () => {
    const notOk = vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) });
    expect(await loadFeed(notOk as unknown as typeof fetch)).toEqual([]);
    const boom = vi.fn().mockRejectedValue(new Error("down"));
    expect(await loadFeed(boom as unknown as typeof fetch)).toEqual([]);
    const ok = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ videos: [good] }) });
    expect(await loadFeed(ok as unknown as typeof fetch)).toHaveLength(1);
  });

  it("builds VideoObject, safe JSON-LD and referral links", () => {
    const v = parseVideo(good)!;
    expect(isoDuration(31.4)).toBe("PT31S");
    expect(isoDuration(65)).toBe("PT1M5S");
    const obj = videoObject(v, "https://menivor.com/made-with-menivor#x");
    expect(obj["@type"]).toBe("VideoObject");
    expect(obj.duration).toBe("PT31S");
    expect(jsonLdText(obj)).not.toContain("</script>");
    const link = new URL(productLink(v));
    expect(link.hostname).toBe("bidstage.app");
    expect(link.searchParams.get("utm_medium")).toBe("referral");
    expect(link.searchParams.get("utm_campaign")).toBe("made-with-menivor");
  });

  it("writes an escaped video sitemap", () => {
    const xml = videoSitemapXml([parseVideo({ ...good, title: "A & B <c>" })!]);
    expect(xml).toContain('xmlns:video="http://www.google.com/schemas/sitemap-video/1.1"');
    expect(xml).toContain("<loc>https://menivor.com/made-with-menivor</loc>");
    expect(xml).toContain("A &amp; B &lt;c&gt;");
    expect(xml).toContain("<video:duration>31</video:duration>");
  });
});
