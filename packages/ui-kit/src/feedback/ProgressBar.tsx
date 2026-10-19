import * as React from "react";
import { colors, radii } from "../tokens/index.js";
export function ProgressBar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div style={{ width: "100%", height: 8, background: colors.surfaceAlt, borderRadius: radii.pill }}>
      <div style={{ width: `${pct}%`, height: "100%", background: colors.primary, borderRadius: radii.pill, transition: "width .2s" }} />
    </div>
  );
}
