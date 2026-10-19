"use client";

import * as React from "react";
import { apply, categoryOf, listKernels } from "@reelforge/effects-core";
import { Badge, Button, Card, colors } from "@reelforge/ui-kit";

/**
 * Effects Lab — scrub time across the real animation kernels from
 * `@reelforge/effects-core` (push-in, ken-burns, handheld, rgb-split, film-grain,
 * shake — byte-identical to the Python `reelforge_effects_core`) and watch both
 * the kernel's raw output values and a live CSS preview driven by them. The
 * transform you see is exactly what the renderer animates. Read-only reference.
 */

/** Map a kernel's output record onto a CSS transform + effect styles. */
function styleFromOutput(out: Record<string, number>): React.CSSProperties {
  const zoom = out.zoom ?? 1;
  const tx = (out.x ?? out.dx ?? 0) * 40; // normalized offsets → preview px
  const ty = (out.y ?? out.dy ?? 0) * 40;
  const rot = out.rot ?? 0;
  const shift = out.shift_px ?? 0;
  const grain = out.grain ?? 0;
  const vignette = out.vignette ?? 0;
  const style: React.CSSProperties = {
    transform: `translate(${tx.toFixed(1)}px, ${ty.toFixed(1)}px) scale(${zoom.toFixed(3)}) rotate(${rot.toFixed(2)}deg)`,
    transformOrigin: "center",
  };
  if (shift) {
    style.textShadow = `${shift.toFixed(1)}px 0 rgba(255,0,0,0.7), ${(-shift).toFixed(1)}px 0 rgba(0,200,255,0.7)`;
  }
  if (grain || vignette) {
    style.filter = `contrast(${1 + grain}) brightness(${1 - vignette * 0.3})`;
  }
  return style;
}

export default function EffectsLabPage() {
  const kernels = React.useMemo(() => listKernels().map((id) => ({ id, category: categoryOf(id) })), []);
  const [selected, setSelected] = React.useState(kernels[0]?.id ?? "push-in");
  const [t, setT] = React.useState(0.5);

  const out = React.useMemo(() => apply(selected, t), [selected, t]);

  return (
    <main style={{ maxWidth: 720, margin: "0 auto", padding: 24, display: "grid", gap: 16, color: colors.textPrimary }}>
      <header style={{ display: "grid", gap: 4 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700 }}>Effects Lab</h1>
        <p style={{ color: colors.muted, fontSize: 14 }}>
          Scrub time across the real animation kernels from <code>@reelforge/effects-core</code> — the
          transform you see is exactly what the renderer animates.
        </p>
      </header>

      <Card>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {kernels.map((k) => (
            <Button key={k.id} variant={selected === k.id ? "primary" : "secondary"} onClick={() => setSelected(k.id)}>
              {k.id}
            </Button>
          ))}
        </div>
      </Card>

      <Card>
        <div style={{ display: "grid", gap: 14 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <Badge tone={categoryOf(selected) === "camera" ? "accent" : "success"}>{categoryOf(selected)}</Badge>
            <span style={{ color: colors.muted, fontSize: 13 }}>t = {t.toFixed(2)}</span>
          </div>

          {/* Live preview: a sample frame under the kernel's current transform. */}
          <div style={{ height: 220, borderRadius: 10, background: "#0d0d15", overflow: "hidden", display: "flex", alignItems: "center", justifyContent: "center", position: "relative" }}>
            <div style={{ ...styleFromOutput(out), width: 160, height: 90, borderRadius: 8, background: "linear-gradient(135deg,#6a5bff,#25f4ee)", display: "flex", alignItems: "center", justifyContent: "center", color: "#0d0d15", fontWeight: 800, fontSize: 18 }}>
              HOOK
            </div>
          </div>

          <input type="range" min={0} max={1} step={0.01} value={t} onChange={(e) => setT(Number(e.target.value))}
            aria-label="time" style={{ width: "100%", accentColor: colors.primary }} />
        </div>
      </Card>

      <Card>
        <div style={{ display: "grid", gap: 8 }}>
          <div style={{ fontSize: 13, color: colors.muted }}>kernel output @ t = {t.toFixed(2)}</div>
          <div style={{ display: "grid", gap: 6 }}>
            {Object.entries(out).map(([k, v]) => (
              <div key={k} style={{ display: "flex", justifyContent: "space-between", fontFamily: "ui-monospace, monospace", fontSize: 13 }}>
                <span style={{ color: colors.textSecondary }}>{k}</span>
                <span>{v.toFixed(4)}</span>
              </div>
            ))}
          </div>
        </div>
      </Card>
    </main>
  );
}
