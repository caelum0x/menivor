import * as React from "react";
import { platformColors, type PlatformColor } from "../tokens/index.js";

const LABEL: Record<PlatformColor, string> = { tiktok: "TT", instagram: "IG", youtube: "YT", x: "X" };

/** Platform brand dot + label (icon glyphs are app-supplied). */
export function PlatformIcon({ platform, size = 20 }: { platform: PlatformColor; size?: number }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center",
      width: size, height: size, borderRadius: 6, background: platformColors[platform],
      color: "#fff", fontSize: size * 0.5, fontWeight: 700 }}>
      {LABEL[platform]}
    </span>
  );
}
