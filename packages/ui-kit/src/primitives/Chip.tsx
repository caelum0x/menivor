import * as React from "react";
import { colors, radii } from "../tokens/index.js";
export function Chip({ label, selected, onClick }: { label: string; selected?: boolean; onClick?: () => void }) {
  return (
    <button onClick={onClick} style={{ border: `1px solid ${selected ? colors.primary : colors.border}`,
      background: selected ? `${colors.primary}22` : "transparent", color: selected ? colors.accent : colors.textSecondary,
      borderRadius: radii.pill, padding: "4px 12px", fontSize: 13, cursor: onClick ? "pointer" : "default" }}>
      {label}
    </button>
  );
}
export function ChipRow({ children }: { children: React.ReactNode }) {
  return <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>{children}</div>;
}
