/** Foreign-watermark cross-post suppression (mirror of `watermark_policy.py`). */

const SUPPRESSED: Record<string, string[]> = {
  instagram: ["tiktok", "musically", "capcut"],
  youtube: ["tiktok", "musically"],
  tiktok: ["instagram", "reels", "youtube", "shorts"],
  x: [],
};

export function isWatermarkAllowed(targetPlatform: string, watermarkSource: string): boolean {
  const src = String(watermarkSource || "").trim().toLowerCase();
  if (!src) return true;
  const suppressed = SUPPRESSED[String(targetPlatform || "").trim().toLowerCase()] ?? [];
  return !suppressed.includes(src);
}

export interface WatermarkCheck {
  allowed: boolean;
  reason: string;
}

export function checkWatermark(targetPlatform: string, watermarkSource: string): WatermarkCheck {
  const allowed = isWatermarkAllowed(targetPlatform, watermarkSource);
  const reason = allowed
    ? ""
    : `${watermarkSource} watermark is suppressed on ${targetPlatform}; ` +
      "re-export a clean version before cross-posting";
  return { allowed, reason };
}
