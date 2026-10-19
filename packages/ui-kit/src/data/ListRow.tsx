import * as React from "react";
import { colors } from "../tokens/index.js";
export function ListRow({ title, subtitle, right }: { title: React.ReactNode; subtitle?: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 0", borderBottom: `1px solid ${colors.border}` }}>
      <div>
        <div style={{ color: colors.textPrimary, fontSize: 14, fontWeight: 600 }}>{title}</div>
        {subtitle ? <div style={{ color: colors.muted, fontSize: 12 }}>{subtitle}</div> : null}
      </div>
      {right}
    </div>
  );
}
