"use client";

import * as React from "react";
import { GATE, hookScore, type HookSignals } from "@reelforge/growth-analytics";
import { Badge, Card, HookScoreGauge, colors } from "@reelforge/ui-kit";

/**
 * Hook Score Lab — an interactive tool over `@reelforge/growth-analytics.hookScore`,
 * the same weighted-signal model (byte-identical to `hook.py`) the pipeline uses to
 * decide whether a reel's first frames clear the 70% hook gate. Drag the four
 * first-3s signals and watch the score, the pass/fail gate, and each signal's
 * weighted contribution update live. Read-only reference; nothing is submitted.
 */

// Mirrors the private WEIGHTS in `growth-analytics/hook.ts` (stable constants) —
// used only to visualize each signal's contribution; the score itself comes from
// the package's `hookScore`, never recomputed here.
const WEIGHTS: Array<{ key: keyof HookSignals; label: string; weight: number }> = [
  { key: "motion", label: "Motion", weight: 0.35 },
  { key: "audio_onset", label: "Audio onset", weight: 0.25 },
  { key: "contrast", label: "Contrast", weight: 0.2 },
  { key: "text", label: "Text", weight: 0.2 },
];

export default function HookLabPage() {
  const [signals, setSignals] = React.useState<Required<HookSignals>>({
    motion: 0.9,
    contrast: 0.8,
    text: 0.7,
    audio_onset: 0.8,
  });

  const result = React.useMemo(() => hookScore(signals), [signals]);
  const set = (key: keyof HookSignals, value: number) =>
    setSignals((prev) => ({ ...prev, [key]: value }));

  return (
    <main style={{ maxWidth: 720, margin: "0 auto", padding: 24, display: "grid", gap: 16, color: colors.textPrimary }}>
      <header style={{ display: "grid", gap: 4 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700 }}>Hook Score Lab</h1>
        <p style={{ color: colors.muted, fontSize: 14 }}>
          The weighted first-3s hook model the pipeline gates on — identical to the renderer via{" "}
          <code>@reelforge/growth-analytics</code>. A reel must clear the {Math.round(GATE * 100)}% gate.
        </p>
      </header>

      <Card>
        <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 20, alignItems: "center" }}>
          <div style={{ display: "grid", justifyItems: "center", gap: 6 }}>
            <HookScoreGauge signals={signals} />
            <Badge tone={result.passes ? "success" : "error"}>
              {result.passes ? "clears gate" : "below gate"}
            </Badge>
          </div>
          <div style={{ display: "grid", gap: 12 }}>
            {WEIGHTS.map(({ key, label, weight }) => {
              const value = signals[key] ?? 0;
              const contribution = weight * value;
              return (
                <div key={key} style={{ display: "grid", gap: 4 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                    <span>
                      {label} <span style={{ color: colors.muted }}>×{weight}</span>
                    </span>
                    <span style={{ color: colors.muted }}>
                      {value.toFixed(2)} → +{contribution.toFixed(3)}
                    </span>
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.01}
                    value={value}
                    onChange={(e) => set(key, Number(e.target.value))}
                    aria-label={label}
                    style={{ width: "100%", accentColor: colors.primary }}
                  />
                </div>
              );
            })}
          </div>
        </div>
      </Card>

      <Card>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
          <div style={{ fontSize: 13, color: colors.muted }}>Hook score</div>
          <div style={{ fontSize: 28, fontWeight: 700, color: result.passes ? colors.success : colors.error }}>
            {Math.round(result.score * 100)}%
          </div>
        </div>
        <div style={{ marginTop: 8, height: 8, borderRadius: 4, background: colors.surfaceAlt, position: "relative" }}>
          <div style={{ position: "absolute", left: `${GATE * 100}%`, top: -4, bottom: -4, width: 2, background: colors.warning }} />
          <div style={{ width: `${Math.min(100, result.score * 100)}%`, height: "100%", borderRadius: 4, background: result.passes ? colors.success : colors.error }} />
        </div>
        <div style={{ marginTop: 6, fontSize: 12, color: colors.muted }}>
          The yellow marker is the {Math.round(GATE * 100)}% gate.
        </div>
      </Card>
    </main>
  );
}
