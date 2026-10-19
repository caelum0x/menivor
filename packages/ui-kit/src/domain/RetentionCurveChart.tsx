import * as React from "react";
import { normalizeCurve, reachTier } from "@reelforge/growth-analytics";
import { colors } from "../tokens/index.js";

/**
 * Per-second retention curve with the first-3s + loop markers. Normalizes raw
 * viewer counts via `@reelforge/growth-analytics` so the chart matches the
 * backend's reach-tier decision exactly.
 */
export function RetentionCurveChart({ samples, width = 320, height = 100 }:
  { samples: number[]; width?: number; height?: number }) {
  const curve = normalizeCurve(samples);
  if (curve.length < 2) return <div style={{ color: colors.muted, fontSize: 12 }}>Not enough data</div>;
  const avg = curve.reduce((a, b) => a + b, 0) / curve.length;
  const tier = reachTier(avg);
  const step = width / (curve.length - 1);
  const pts = curve.map((v, i) => `${(i * step).toFixed(1)},${(height - v * height).toFixed(1)}`).join(" ");
  const x3s = Math.min(3, curve.length - 1) * step;
  const tierColor = tier.tier === "viral" ? colors.success : tier.tier === "boosted" ? colors.accent : colors.muted;
  return (
    <div>
      <svg width={width} height={height} style={{ display: "block" }}>
        <polyline points={pts} fill="none" stroke={tierColor} strokeWidth={2} />
        <line x1={x3s} y1={0} x2={x3s} y2={height} stroke={colors.warning} strokeDasharray="3 3" />
      </svg>
      <div style={{ color: tierColor, fontSize: 12, marginTop: 4 }}>
        {Math.round(avg * 100)}% avg · {tier.tier} ({tier.multiplier}× reach)
      </div>
    </div>
  );
}
