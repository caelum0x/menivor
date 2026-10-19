import { describe, expect, it } from "vitest";

import {
  EMPTY_MANUAL,
  MAX_BATCH,
  captionsSheet,
  describeBatch,
  editableAngles,
  estimateBatch,
  formatPrice,
  isActive,
  manualToInput,
  productToInput,
  toggleIn,
  validateAnalyze,
  type AdAngle,
  type Product,
} from "../api";

const product: Product = {
  url: "https://shop.com/p/1",
  source: "shopify",
  title: "Trail Bottle",
  brand: "Hike Co",
  description: "Insulated steel bottle",
  price: 24,
  original_price: 30,
  currency: "USD",
  images: Array.from({ length: 12 }, (_, i) => `https://cdn.shop.com/${i}.jpg`),
  bullets: Array.from({ length: 10 }, (_, i) => `Feature ${i}`),
  rating: 4.6,
  review_count: 120,
  reviews: Array.from({ length: 9 }, (_, i) => `Review ${i}`),
  language: "en",
};

describe("estimateBatch", () => {
  it("counts free and avatar ads and the reel credits they use", () => {
    const estimate = estimateBatch(3, ["showcase", "ugc_avatar"], 2);
    expect(estimate).toEqual({ total: 12, free: 6, avatarAds: 6, credits: 6, overLimit: false });
    expect(describeBatch(estimate)).toBe(
      "12 ads: 6 free, 6 avatar (6 reel credits when you start them).",
    );
  });

  it("renders showcase and before/after batches for free", () => {
    const estimate = estimateBatch(2, ["showcase", "before_after"], 1);
    expect(estimate.credits).toBe(0);
    expect(describeBatch(estimate)).toBe("4 ads, rendered free.");
  });

  it("flags empty and oversized batches", () => {
    expect(describeBatch(estimateBatch(0, ["showcase"], 1))).toContain("Pick at least one");
    const big = estimateBatch(5, ["showcase", "before_after", "ugc_avatar"], 3);
    expect(big.total).toBe(45);
    expect(big.overLimit).toBe(true);
    expect(describeBatch(big)).toContain(`${MAX_BATCH}-ad limit`);
  });

  it("describes an avatar-only batch", () => {
    expect(describeBatch(estimateBatch(1, ["ugc_avatar"], 1))).toBe(
      "1 ad: 1 avatar (1 reel credit when you start them).",
    );
  });
});

describe("product helpers", () => {
  it("caps product input lists the way the API expects", () => {
    const input = productToInput(product);
    expect(input.images).toHaveLength(10);
    expect(input.bullets).toHaveLength(8);
    expect(input.reviews).toHaveLength(6);
    expect(input.source).toBe("shopify");
  });

  it("strips angles down to their editable fields", () => {
    const angle: AdAngle = {
      id: "a1",
      kind: "pain",
      label: "Pain point",
      hook: "Tired of warm water?",
      pain: "p",
      proof: "q",
      offer: "o",
      cta: "c",
      benefits: ["x"],
      script: "s",
      source: "llm",
    };
    expect(editableAngles([angle])).toEqual([
      { kind: "pain", hook: "Tired of warm water?", pain: "p", proof: "q", offer: "o", cta: "c", source: "llm" },
    ]);
  });

  it("parses manual product details and drops non-http image lines", () => {
    const input = manualToInput({
      ...EMPTY_MANUAL,
      title: "  Mug ",
      price: "12,50",
      originalPrice: "abc",
      bullets: "Holds 350 ml\n\n Dishwasher safe ",
      images: "https://cdn.x/1.jpg\njavascript:alert(1)\nftp://x/2.jpg",
    });
    expect(input.title).toBe("Mug");
    expect(input.price).toBe(12.5);
    expect(input.original_price).toBeNull();
    expect(input.bullets).toEqual(["Holds 350 ml", "Dishwasher safe"]);
    expect(input.images).toEqual(["https://cdn.x/1.jpg"]);
  });

  it("validates the analyze form", () => {
    expect(validateAnalyze("url", "shop.com", EMPTY_MANUAL)).toContain("https://");
    expect(validateAnalyze("url", "https://shop.com/p/1", EMPTY_MANUAL)).toBe("");
    expect(validateAnalyze("manual", "", EMPTY_MANUAL)).toBe("Enter the product name.");
    expect(validateAnalyze("manual", "", { ...EMPTY_MANUAL, title: "Mug" })).toBe("");
  });

  it("formats prices and hides empty ones", () => {
    expect(formatPrice(24, "USD", "en")).toBe("$24.00");
    expect(formatPrice(null, "USD", "en")).toBe("");
  });
});

describe("misc helpers", () => {
  it("toggles list membership without mutating", () => {
    const list = ["a", "b"];
    expect(toggleIn(list, "b")).toEqual(["a"]);
    expect(toggleIn(list, "c")).toEqual(["a", "b", "c"]);
    expect(list).toEqual(["a", "b"]);
  });

  it("treats queued, rendering and submitted ads as active", () => {
    expect(isActive("queued")).toBe(true);
    expect(isActive("submitted")).toBe(true);
    expect(isActive("ready")).toBe(false);
    expect(isActive("done")).toBe(false);
  });

  it("builds a plain-text captions sheet", () => {
    expect(
      captionsSheet({
        project_id: "p1",
        title: "Bottle",
        pending: 0,
        items: [
          {
            variant_id: "v1",
            filename: "bottle-1.mp4",
            download_url: "https://x/1.mp4",
            format: "showcase",
            aspect: "9:16",
            angle_label: "Pain point",
            script: "s",
            post_caption: "Cold for 24 hours.",
          },
        ],
      }),
    ).toBe("bottle-1.mp4 (Pain point, 9:16)\nCold for 24 hours.");
  });
});
