"use client";

import * as React from "react";
import { dropoff, normalizeCurve, reachTier } from "@reelforge/growth-analytics";
import { Badge, Button, Card, RetentionCurveChart, StatTile, colors } from "@reelforge/ui-kit";

/**
 * Retention Lab — paste a per-second viewer curve and see how the pipeline reads
 * it: the normalized curve, the reach tier + boost multiplier, and the drop-off
 * analysis (biggest single-second cliff + first-3s average). All from the real
 * `@reelforge/growth-analytics` retention model (byte-identical to `retention.py`).
 * Read-only analysis; nothing is submitted.
 */

const PRESETS: Array<{ label: string; samples: number[] }> = [
  { label: "Viral", samples: [1000, 980, 960, 950, 945, 940, 935, 930, 925, 920] },
  { label: "Steep cliff", samples: [1000, 940, 500, 460, 440, 430, 420, 410, 405, 400] },
  { label: "Slow bleed", samples: [1000, 900, 820, 740, 660, 590, 520, 460, 410, 370] },
];

function parseSamples(text: string): number[] {
  return text
    .split(/[,\s]+/)
    .map((t) => Number(t.trim()))
    .filter((n) => Number.isFinite(n) && n >= 0);
}

export default function RetentionLabPage() {
  const [text, setText] = React.useState(PRESETS[0]!.samples.join(", "));
  const samples = React.useMemo(() => parseSamples(text), [text]);

  const { curve, tier, drop, avg } = React.useMemo(() => {
    const curve = normalizeCurve(samples);
    const avg = curve.length ? curve.reduce((a, b) => a + b, 0) / curve.length : 0;
    return { curve, tier: reachTier(avg), drop: dropoff(curve), avg };
  }, [samples]);

  const tierTone = tier.tier === "viral" ? "success" : tier.tier === "boosted" ? "accent" : "warning";

  return (
    <main style={{ maxWidth: 720, margin: "0 auto", padding: 24, display: "grid", gap: 16, color: colors.textPrimary }}>
      <header style={{ display: "grid", gap: 4 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700 }}>Retention Lab</h1>
        <p style={{ color: colors.muted, fontSize: 14 }}>
          Paste a per-second viewer curve; the reach tier + drop-off come from the real{" "}
          <code>@reelforge/growth-analytics</code> model the pipeline scores with.
        </p>
      </header>

      <Card>
        <div style={{ display: "grid", gap: 10 }}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {PRESETS.map((p) => (
              <Button key={p.label} variant="secondary" onClick={() => setText(p.samples.join(", "))}>
                {p.label}
              </Button>
            ))}
          </div>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            aria-label="Per-second viewer samples"
            rows={2}
            style={{
              width: "100%", resize: "vertical", background: colors.surfaceAlt, color: colors.textPrimary,
              border: `1px solid ${colors.border}`, borderRadius: 8, padding: 10, fontFamily: "ui-monospace, monospace", fontSize: 13,
            }}
          />
          <div style={{ fontSize: 12, color: colors.muted }}>{samples.length} samples (comma or space separated)</div>
        </div>
      </Card>

      {samples.length >= 2 ? (
        <>
          <Card>
            <div style={{ display: "grid", gap: 10 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <div style={{ fontSize: 13, color: colors.muted }}>Normalized retention</div>
                <Badge tone={tierTone}>{tier.tier} · {tier.multiplier}× reach</Badge>
              </div>
              <RetentionCurveChart samples={samples} width={640} height={120} />
            </div>
          </Card>

          <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(3, 1fr)" }}>
            <StatTile label="Avg retention" value={`${Math.round(avg * 100)}%`} accent />
            <StatTile label="First 3s" value={`${Math.round(drop.first_3s * 100)}%`} />
            <StatTile label="Biggest drop" value={`${Math.round(drop.max_drop * 100)}% @ ${drop.max_drop_at}s`} />
          </div>
        </>
      ) : (
        <Card>
          <div style={{ color: colors.muted, fontSize: 13, padding: 4 }}>Enter at least two samples to analyze.</div>
        </Card>
      )}
    </main>
  );
}
