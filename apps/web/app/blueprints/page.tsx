"use client";

import * as React from "react";
import {
  getPreset,
  listPresets,
  totalDurationMs,
  type ShotTemplate,
} from "@reelforge/shot-template-schema";
import { Badge, Card, SegmentSlotBar, colors } from "@reelforge/ui-kit";

/**
 * Shot Blueprints — the structural templates (hook → rising → payoff → loop) that
 * drive every genre. Reads the real presets from `@reelforge/shot-template-schema`
 * (the same package the API and desktop compose against) and renders each one's
 * slot timeline with the shared `SegmentSlotBar`, so the blueprint a creator sees
 * here is byte-identical to what the renderer uses. Pure read-only reference.
 */
export default function BlueprintsPage() {
  // The preset registry is static + deterministic; resolve once.
  const templates = React.useMemo<ShotTemplate[]>(
    () => listPresets().map((slug) => getPreset(slug)),
    [],
  );

  return (
    <main style={{ maxWidth: 820, margin: "0 auto", padding: 24, display: "grid", gap: 16, color: colors.textPrimary }}>
      <header style={{ display: "grid", gap: 4 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700 }}>Shot Blueprints</h1>
        <p style={{ color: colors.muted, fontSize: 14 }}>
          The structural templates the renderer composes against — timings are integer-millisecond and
          identical across the API, web, and desktop.
        </p>
      </header>

      {templates.map((t) => {
        const durationS = (totalDurationMs(t) / 1000).toFixed(1);
        return (
          <Card key={t.slug}>
            <div style={{ display: "grid", gap: 10 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                <div style={{ fontWeight: 600 }}>{t.slug}</div>
                <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  <Badge tone="accent">{t.genre}</Badge>
                  <Badge>{t.aspect}</Badge>
                  <span style={{ color: colors.muted, fontSize: 12 }}>{durationS}s</span>
                </div>
              </div>
              <SegmentSlotBar slots={t.slots} />
              <div style={{ color: colors.muted, fontSize: 12 }}>
                {t.slots.length} slot{t.slots.length === 1 ? "" : "s"} ·{" "}
                {t.slots.map((s) => s.role).join(" → ")}
              </div>
            </div>
          </Card>
        );
      })}
    </main>
  );
}
