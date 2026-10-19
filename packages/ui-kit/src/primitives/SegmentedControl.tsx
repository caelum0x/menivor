import * as React from "react";
import { colors, radii } from "../tokens/index.js";
export function SegmentedControl<T extends string>({ options, value, onChange }:
  { options: { value: T; label: string }[]; value: T; onChange: (v: T) => void }) {
  return (
    <div style={{ display: "inline-flex", background: colors.surfaceAlt, borderRadius: radii.md, padding: 2 }}>
      {options.map((o) => (
        <button key={o.value} onClick={() => onChange(o.value)}
          style={{ border: "none", cursor: "pointer", borderRadius: radii.sm, padding: "6px 14px", fontSize: 13, fontWeight: 600,
            background: value === o.value ? colors.primary : "transparent",
            color: value === o.value ? colors.bg : colors.textSecondary }}>
          {o.label}
        </button>
      ))}
    </div>
  );
}
