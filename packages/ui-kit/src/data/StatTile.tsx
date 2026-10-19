import * as React from "react";
import { colors, radii, spacing } from "../tokens/index.js";
export function StatTile({ label, value, accent }: { label: string; value: React.ReactNode; accent?: boolean }) {
  return (
    <div style={{ background: colors.surface, border: `1px solid ${colors.border}`, borderRadius: radii.lg, padding: spacing.lg }}>
      <div style={{ color: colors.muted, fontSize: 12 }}>{label}</div>
      <div style={{ color: accent ? colors.success : colors.textPrimary, fontSize: 24, fontWeight: 700 }}>{value}</div>
    </div>
  );
}
