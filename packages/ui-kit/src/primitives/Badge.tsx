import * as React from "react";
import { colors, radii } from "../tokens/index.js";

export type BadgeTone = "neutral" | "success" | "warning" | "error" | "accent";
const TONE: Record<BadgeTone, string> = {
  neutral: colors.muted, success: colors.success, warning: colors.warning,
  error: colors.error, accent: colors.accent,
};

/** Small status badge. */
export function Badge({ tone = "neutral", children }: { tone?: BadgeTone; children: React.ReactNode }) {
  return (
    <span style={{ background: `${TONE[tone]}22`, color: TONE[tone],
      borderRadius: radii.pill, padding: "2px 8px", fontSize: 11, fontWeight: 600 }}>
      {children}
    </span>
  );
}
