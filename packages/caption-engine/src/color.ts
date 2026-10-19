/** Hex → ASS `&HAABBGGRR` colour (mirror of `color.py`). Alpha 0 = opaque. */

function hex2(n: number): string {
  return n.toString(16).toUpperCase().padStart(2, "0");
}

export function hexToAss(hexColor: string, alpha = 0): string {
  const h = hexColor.replace(/^#/, "");
  if (h.length !== 6) throw new Error(`expected #RRGGBB, got ${hexColor}`);
  const rr = parseInt(h.slice(0, 2), 16);
  const gg = parseInt(h.slice(2, 4), 16);
  const bb = parseInt(h.slice(4, 6), 16);
  const a = Math.max(0, Math.min(255, Math.trunc(alpha)));
  return `&H${hex2(a)}${hex2(bb)}${hex2(gg)}${hex2(rr)}`;
}
