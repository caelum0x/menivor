import * as React from "react";
import { colors } from "../tokens/index.js";
import { formatUsdMicros } from "../format/index.js";
/** Credits/$ burn badge for a generation — the "keepers-left" burn-preview hint. */
export function BurnPreviewBadge({ costMicros, keepersLeft }: { costMicros: number; keepersLeft?: number }) {
  return (
    <span style={{ display: "inline-flex", gap: 8, alignItems: "center", background: colors.surfaceAlt,
      borderRadius: 999, padding: "3px 10px", fontSize: 12, color: colors.textSecondary }}>
      <span style={{ color: colors.textPrimary, fontWeight: 600 }}>{formatUsdMicros(costMicros)}</span>
      {typeof keepersLeft === "number" ? <span>· {keepersLeft} keepers left</span> : null}
    </span>
  );
}
