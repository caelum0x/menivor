import * as React from "react";
import { colors } from "../tokens/index.js";
export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div style={{ textAlign: "center", padding: 32 }}>
      <div style={{ color: colors.textPrimary, fontSize: 15, fontWeight: 600 }}>{title}</div>
      {hint ? <div style={{ color: colors.muted, fontSize: 13, marginTop: 4 }}>{hint}</div> : null}
    </div>
  );
}
