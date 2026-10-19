/**
 * Convert an ASS `&HAABBGGRR` colour for the reel-create caption preview (as returned by GET /catalog/caption-styles
 * — alpha, blue, green, red; `00` alpha = fully opaque) into a CSS `rgba(...)`
 * string usable in a swatch. Falls back to opaque white for missing/invalid
 * input so a swatch always renders something.
 */
export function assColorToCss(ass: string | undefined, fallback = "#ffffff"): string {
  if (!ass) return fallback;

  const cleaned = ass.trim().replace(/^&H/i, "").replace(/&$/, "");
  if (!/^[0-9a-fA-F]{1,8}$/.test(cleaned)) return fallback;

  // Right-pad to AABBGGRR; a 6-digit value has no alpha byte (assume opaque).
  const hex = cleaned.padStart(8, "0");
  const aa = Number.parseInt(hex.slice(0, 2), 16);
  const bb = Number.parseInt(hex.slice(2, 4), 16);
  const gg = Number.parseInt(hex.slice(4, 6), 16);
  const rr = Number.parseInt(hex.slice(6, 8), 16);

  // ASS alpha is inverted vs. CSS: 0x00 = opaque, 0xFF = transparent.
  const alpha = Math.round(((255 - aa) / 255) * 1000) / 1000;
  return `rgba(${rr}, ${gg}, ${bb}, ${alpha})`;
}
