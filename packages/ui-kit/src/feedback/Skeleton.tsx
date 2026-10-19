import * as React from "react";
import { colors, radii } from "../tokens/index.js";
export function Skeleton({ width = "100%", height = 16 }: { width?: number | string; height?: number }) {
  return <div style={{ width, height, background: colors.surfaceAlt, borderRadius: radii.sm, opacity: 0.6 }} />;
}
