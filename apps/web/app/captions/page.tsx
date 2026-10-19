"use client";

import * as React from "react";
import { getPreset, listPresets, type CaptionStyle } from "@reelforge/caption-engine";
import { Badge, Card, colors } from "@reelforge/ui-kit";

/**
 * Caption Styles — a live reference for the burned-in caption presets from
 * `@reelforge/caption-engine` (the same registry the API and desktop render ASS
 * subtitles from). Each preview approximates the preset's ASS style in the DOM
 * (font, weight, casing, primary + highlight colors, outline/shadow) so a creator
 * can pick a look before rendering. Read-only reference; no fabricated data.
 */

/** ASS numpad alignment → a human label for the position badge. */
function alignmentLabel(alignment: number): string {
  if (alignment >= 7) return "top";
  if (alignment >= 4) return "middle";
  return "bottom";
}

/** Approximate the ASS outline+shadow as a layered CSS text-shadow. */
function textShadow(style: CaptionStyle): string {
  const o = style.outline;
  const layers = [
    `-${o}px 0 ${style.outline_hex}`,
    `${o}px 0 ${style.outline_hex}`,
    `0 -${o}px ${style.outline_hex}`,
    `0 ${o}px ${style.outline_hex}`,
  ];
  if (style.shadow > 0) {
    layers.push(`${style.shadow}px ${style.shadow}px ${style.shadow}px rgba(0,0,0,0.6)`);
  }
  return layers.join(", ");
}

function CaptionPreview({ style }: { style: CaptionStyle }) {
  // ASS sizes are full-res (e.g. 120); scale down for an on-screen preview.
  const fontSize = Math.max(16, Math.round(style.size / 4));
  const words = ["THIS", "changed", "everything"];
  return (
    <div
      style={{
        background: "#111119",
        borderRadius: 8,
        padding: "20px 16px",
        textAlign: "center",
        minHeight: 96,
        display: "flex",
        alignItems: alignmentLabel(style.alignment) === "top" ? "flex-start" : alignmentLabel(style.alignment) === "middle" ? "center" : "flex-end",
        justifyContent: "center",
      }}
    >
      <div
        style={{
          fontFamily: `"${style.font}", system-ui, sans-serif`,
          fontSize,
          fontWeight: style.bold ? 800 : 500,
          textTransform: style.uppercase ? "uppercase" : "none",
          color: style.primary_hex,
          textShadow: textShadow(style),
          lineHeight: 1.1,
          letterSpacing: 0.5,
        }}
      >
        {words.map((w, i) => (
          <span key={i} style={{ color: i === 1 ? style.highlight_hex : style.primary_hex }}>
            {w}
            {i < words.length - 1 ? " " : ""}
          </span>
        ))}
      </div>
    </div>
  );
}

export default function CaptionsPage() {
  const presets = React.useMemo(
    () => listPresets().map((name) => ({ name, style: getPreset(name) })),
    [],
  );

  return (
    <main style={{ maxWidth: 820, margin: "0 auto", padding: 24, display: "grid", gap: 16, color: colors.textPrimary }}>
      <header style={{ display: "grid", gap: 4 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700 }}>Caption Styles</h1>
        <p style={{ color: colors.muted, fontSize: 14 }}>
          The burned-in caption presets the renderer uses — the same registry across the API, web, and
          desktop. Each preview approximates the ASS style; the highlighted word shows the karaoke color.
        </p>
      </header>

      <div style={{ display: "grid", gap: 16, gridTemplateColumns: "repeat(2, 1fr)" }}>
        {presets.map(({ name, style }) => (
          <Card key={name}>
            <div style={{ display: "grid", gap: 10 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                <div style={{ fontWeight: 600 }}>{name}</div>
                <div style={{ display: "flex", gap: 6 }}>
                  <Badge tone="accent">{alignmentLabel(style.alignment)}</Badge>
                  <Badge>{style.words_per_group}/grp</Badge>
                </div>
              </div>
              <CaptionPreview style={style} />
              <div style={{ color: colors.muted, fontSize: 12 }}>
                {style.font} · {style.size}px · outline {style.outline}
                {style.uppercase ? " · UPPERCASE" : ""}
              </div>
            </div>
          </Card>
        ))}
      </div>
    </main>
  );
}
