import * as React from "react";
import { colors } from "../tokens/index.js";
export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return <div style={{ color: colors.muted, fontSize: 13, padding: 24, textAlign: "center" }}>{label}</div>;
}
