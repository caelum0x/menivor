import * as React from "react";
import { colors } from "../tokens/index.js";
export function KeyValueRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "10px 0", borderBottom: `1px solid ${colors.border}` }}>
      <span style={{ color: colors.textSecondary, fontSize: 14 }}>{label}</span>
      <span style={{ color: colors.textPrimary, fontSize: 14, fontWeight: 600 }}>{value}</span>
    </div>
  );
}
