import * as React from "react";
import { colors, radii } from "../tokens/index.js";
export function Stepper({ value, min = 0, max = 100, step = 1, onChange }:
  { value: number; min?: number; max?: number; step?: number; onChange: (v: number) => void }) {
  const btn = { width: 32, height: 32, borderRadius: radii.sm, border: "none", cursor: "pointer",
    background: colors.surfaceAlt, color: colors.textPrimary, fontSize: 18, fontWeight: 700 } as const;
  return (
    <div style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
      <button style={btn} onClick={() => onChange(Math.max(min, value - step))}>−</button>
      <span style={{ minWidth: 40, textAlign: "center", color: colors.textPrimary }}>{value}</span>
      <button style={btn} onClick={() => onChange(Math.min(max, value + step))}>+</button>
    </div>
  );
}
