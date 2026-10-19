import * as React from "react";
import { colors } from "../tokens/index.js";
/** Pure relative-time formatter (deterministic given `now`). */
export function relativeTime(iso: string, now: number): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "";
  const s = Math.max(0, Math.round((now - then) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60); if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60); if (h < 24) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}
export function RelativeTime({ iso, now }: { iso: string; now: number }) {
  return <span style={{ color: colors.muted, fontSize: 12 }}>{relativeTime(iso, now)}</span>;
}
