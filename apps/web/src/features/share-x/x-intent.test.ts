import twitterText from "twitter-text";
import { describe, expect, it } from "vitest";
import {
  X_INTENT_ENDPOINT,
  X_WEIGHTED_LIMIT,
  buildXIntent,
  chooseShareHook,
  composedShareTweet,
} from "./x-intent";

function parsed(text: string, url: string) {
  return twitterText.parseTweet(composedShareTweet(text, url));
}

describe("chooseShareHook", () => {
  it("uses the chosen hook, otherwise the first non-empty one", () => {
    expect(chooseShareHook({ chosen: "Picked line", hooks: ["First", "Second"] })).toBe(
      "Picked line",
    );
    expect(chooseShareHook({ chosen: "   ", hooks: ["  ", "First line", "Second"] })).toBe(
      "First line",
    );
    expect(chooseShareHook({ hooks: [] })).toBe("");
  });
});

describe("buildXIntent", () => {
  it("opens the X web intent with the hook, hashtags, and source link", () => {
    const intent = buildXIntent({
      hook: "Stop scrolling.",
      hashtags: ["reels", "#shop"],
      sourceUrl: "https://shop.example/products/mug",
    });

    expect(intent.href.startsWith(`${X_INTENT_ENDPOINT}?`)).toBe(true);
    const parsedUrl = new URL(intent.href);
    expect(parsedUrl.searchParams.get("text")).toBe("Stop scrolling.\n\n#reels #shop");
    expect(parsedUrl.searchParams.get("url")).toBe("https://shop.example/products/mug");
    expect(intent.weightedLength).toBeLessThanOrEqual(X_WEIGHTED_LIMIT);
    expect(parsed(intent.text, intent.url).valid).toBe(true);
  });

  it("percent-encodes Turkish characters and emoji", () => {
    const hook = "Şimdi dene 🎬";
    const intent = buildXIntent({
      hook,
      hashtags: ["ürün"],
      sourceUrl: "https://shop.example/ürünler",
    });

    expect(intent.href).toContain(encodeURIComponent(hook));
    expect(intent.href).toContain("%C5%9E");
    expect(intent.href).toContain("%F0%9F%8E%AC");
    expect(intent.href).not.toContain("Ş");
    expect(intent.href).not.toContain("🎬");

    const parsedUrl = new URL(intent.href);
    expect(parsedUrl.searchParams.get("text")).toContain(hook);
    expect(parsedUrl.searchParams.get("text")).toContain("#ürün");
    expect(parsedUrl.searchParams.get("url")).toContain("shop.example");
    expect(parsed(intent.text, intent.url).valid).toBe(true);
  });

  it("counts the source link as 23 weighted characters", () => {
    const hook = "a".repeat(250);
    const sourceUrl = `https://example.com/${"b".repeat(180)}`;
    const intent = buildXIntent({ hook, sourceUrl });

    expect(intent.text).toBe(hook);
    expect(parsed(intent.text, intent.url).weightedLength).toBe(250 + 1 + 23);
    expect(parsed(intent.text, intent.url).valid).toBe(true);
  });

  it("truncates a long hook on a word boundary and stays within 280", () => {
    const sentence = "Stop scrolling if your shop still does this every morning";
    const hook = Array.from({ length: 40 }, () => sentence).join(" ");
    const intent = buildXIntent({
      hook,
      hashtags: ["shop"],
      sourceUrl: "https://shop.example/products/mug",
    });
    const tweet = composedShareTweet(intent.text, intent.url);
    const result = twitterText.parseTweet(tweet);

    expect(result.valid).toBe(true);
    expect(result.weightedLength).toBeLessThanOrEqual(X_WEIGHTED_LIMIT);
    const hookLine = intent.text.split("\n\n")[0] ?? "";
    expect(hookLine.endsWith("…")).toBe(true);

    const kept = hookLine.slice(0, -"…".length);
    expect(hook.startsWith(kept)).toBe(true);
    expect(hook.charAt(kept.length)).toBe(" ");
  });

  it("truncates a single long word and an emoji-heavy hook without exceeding the limit", () => {
    const word = buildXIntent({
      hook: "x".repeat(500),
      sourceUrl: "https://example.com/x",
    });
    expect(word.text.endsWith("…")).toBe(true);
    expect(parsed(word.text, word.url).valid).toBe(true);
    expect(parsed(word.text, word.url).weightedLength).toBeLessThanOrEqual(X_WEIGHTED_LIMIT);

    const emoji = buildXIntent({ hook: "🎬".repeat(150) });
    expect(emoji.text.endsWith("…")).toBe(true);
    expect(parsed(emoji.text, emoji.url).valid).toBe(true);
    expect(parsed(emoji.text, emoji.url).weightedLength).toBeLessThanOrEqual(X_WEIGHTED_LIMIT);
    expect(emoji.text.includes("🎬")).toBe(true);
  });

  it("shortens the hook to keep hashtags, and drops tags from the end when the list itself does not fit", () => {
    const shortened = buildXIntent({
      hook: "b".repeat(250),
      hashtags: ["alpha", "beta", "gamma"],
      sourceUrl: "https://example.com/path",
    });
    expect(shortened.text).toContain("#alpha #beta #gamma");
    expect(shortened.text.startsWith("b")).toBe(true);
    expect(shortened.text.split("\n\n")[0]?.endsWith("…")).toBe(true);
    expect(parsed(shortened.text, shortened.url).valid).toBe(true);

    const tags = Array.from({ length: 40 }, (_, index) => `tag${index}extra`);
    const dropped = buildXIntent({
      hook: "Hello",
      hashtags: tags,
      sourceUrl: "https://example.com/path",
    });
    const included = [...dropped.text.matchAll(/#(\w+)/g)].map((match) => match[1] ?? "");
    expect(parsed(dropped.text, dropped.url).valid).toBe(true);
    expect(included.length).toBeGreaterThan(0);
    expect(included.length).toBeLessThan(tags.length);
    expect(included).toEqual(tags.slice(0, included.length));
    expect(dropped.text.startsWith("Hello")).toBe(true);

    const cleaned = buildXIntent({
      hook: "Hello",
      hashtags: ["ok", "not a tag", "#ok", ""],
    });
    expect(cleaned.text).toBe("Hello\n\n#ok");
  });

  it("rejects non-http source links and still opens a composer for a hook alone", () => {
    const blocked = buildXIntent({
      hook: "Hi",
      sourceUrl: "javascript:alert(1)",
    });
    expect(blocked.url).toBe("");
    expect(blocked.href).not.toContain("javascript");
    expect(new URL(blocked.href).searchParams.get("text")).toBe("Hi");

    const blank = buildXIntent({ hook: "  ", sourceUrl: "file:///etc/passwd" });
    expect(blank.href).toBe(X_INTENT_ENDPOINT);
    expect(blank.weightedLength).toBe(0);
  });

  it("prefers the chosen hook over the generated list", () => {
    const intent = buildXIntent({
      hook: "Chosen hook",
      hooks: ["First generated", "Second"],
      sourceUrl: "https://example.com",
    });
    expect(intent.text.startsWith("Chosen hook")).toBe(true);
    expect(intent.text).not.toContain("First generated");
  });
});
