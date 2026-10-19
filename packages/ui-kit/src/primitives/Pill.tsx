import * as React from "react";
import { colors, radii } from "../tokens/index.js";
export function Pill({ children }: { children: React.ReactNode }) {
  return <span style={{ background: colors.surfaceAlt, color: colors.textSecondary, borderRadius: radii.pill,
    padding: "2px 10px", fontSize: 12 }}>{children}</span>;
}
