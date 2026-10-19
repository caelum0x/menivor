"use client";

import * as React from "react";
import { Check } from "lucide-react";
import { adSafe, score } from "@reelforge/trends-schema";
import { Badge, Button, Card, StatTile, colors } from "@reelforge/ui-kit";

/**
 * Trend Lab — paste a sound's daily-usage series and read the pipeline's trend
 * signals: saturation, velocity, decay, and the headline **opportunity** score
 * (build-to-it-before-it-peaks), plus the cross-platform ad-safe rule. All from
 * the real `@reelforge/trends-schema` scoring (bit-identical to `scoring.py`).
 * Read-only reference; nothing is submitted.
 */

const PRESETS: Array<{ label: string; series: number[] }> = [
  { label: "Rising", series: [10, 18, 30, 55, 95, 160, 250] },
  { label: "Peaked", series: [40, 120, 300, 520, 610, 605, 600] },
  { label: "Saturated", series: [500, 700, 850, 900, 905, 900, 895] },
  { label: "Fading", series: [900, 820, 640, 470, 330, 220, 140] },
];

function parseSeries(text: string): number[] {
  return text
    .split(/[,\s]+/)
    .map((t) => Number(t.trim()))
    .filter((n) => Number.isFinite(n) && n >= 0);
}

function Sparkline({ series }: { series: number[] }) {
  const peak = Math.max(...series, 1);
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 80 }}>
      {series.map((v, i) => (
        <div key={i} title={String(v)} style={{ flex: 1, minHeight: 2, height: `${Math.max(2, (v / peak) * 100)}%`, borderRadius: 2, background: i === series.length - 1 ? colors.primary : colors.accent }} />
      ))}
    </div>
  );
}

export default function TrendLabPage() {
  const [text, setText] = React.useState(PRESETS[0]!.series.join(", "));
  const [licensed, setLicensed] = React.useState(true);
  const [explicit, setExplicit] = React.useState(false);
  const series = React.useMemo(() => parseSeries(text), [text]);

  const s = React.useMemo(() => (series.length >= 2 ? score(series) : null), [series]);
  const safe = adSafe({ licensed, explicit });

  const oppColor = (o: number): string => {
    if (o >= 0.66) return colors.success;
    if (o >= 0.4) return colors.accent;
    return colors.warning;
  };

  return (
    <main style={{ maxWidth: 720, margin: "0 auto", padding: 24, display: "grid", gap: 16, color: colors.textPrimary }}>
      <header style={{ display: "grid", gap: 4 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700 }}>Trend Lab</h1>
        <p style={{ color: colors.muted, fontSize: 14 }}>
          Paste a sound&apos;s daily-usage series; the signals come from the real{" "}
          <code>@reelforge/trends-schema</code> scoring the pipeline ranks rising audio with.
        </p>
      </header>

      <Card>
        <div style={{ display: "grid", gap: 10 }}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {PRESETS.map((p) => (
              <Button key={p.label} variant="secondary" onClick={() => setText(p.series.join(", "))}>
                {p.label}
              </Button>
            ))}
          </div>
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} aria-label="Daily usage series"
            style={{ width: "100%", resize: "vertical", background: colors.surfaceAlt, color: colors.textPrimary, border: `1px solid ${colors.border}`, borderRadius: 8, padding: 10, fontFamily: "ui-monospace, monospace", fontSize: 13 }} />
          <div style={{ fontSize: 12, color: colors.muted }}>{series.length} data points</div>
          {series.length >= 2 ? <Sparkline series={series} /> : null}
        </div>
      </Card>

      {s ? (
        <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(2, 1fr)" }}>
          <StatTile label="Opportunity" value={<span style={{ color: oppColor(s.opportunity) }}>{Math.round(s.opportunity * 100)}%</span>} accent />
          <StatTile label="Velocity" value={s.velocity.toFixed(3)} />
          <StatTile label="Saturation" value={`${Math.round(s.saturation * 100)}%`} />
          <StatTile label="Decay" value={`${Math.round(s.decay * 100)}%`} />
        </div>
      ) : (
        <Card><div style={{ color: colors.muted, fontSize: 13, padding: 4 }}>Enter at least two data points.</div></Card>
      )}

      <Card>
        <div style={{ display: "grid", gap: 10 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div style={{ fontSize: 14, fontWeight: 600 }}>Ad-safe check</div>
            <Badge tone={safe ? "success" : "error"}>{safe ? "ad-safe" : "not ad-safe"}</Badge>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <Button variant={licensed ? "primary" : "ghost"} onClick={() => setLicensed((v) => !v)}>
              {licensed ? <Check size={14} aria-hidden style={{ marginRight: 4, verticalAlign: "-2px" }} /> : null}Licensed
            </Button>
            <Button variant={explicit ? "danger" : "ghost"} onClick={() => setExplicit((v) => !v)}>
              {explicit ? <Check size={14} aria-hidden style={{ marginRight: 4, verticalAlign: "-2px" }} /> : null}Explicit
            </Button>
          </div>
          <div style={{ fontSize: 12, color: colors.muted }}>
            Cross-platform (Meta-compatible) rule: licensed <strong>and</strong> not explicit.
          </div>
        </div>
      </Card>
    </main>
  );
}
