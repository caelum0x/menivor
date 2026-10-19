"use client";

import * as React from "react";
import { Check } from "lucide-react";
import {
  buildFiltergraph,
  hasAudioOut,
  makeSpec,
  validateSpec,
  videoOutLabel,
  type MakeSpecOptions,
} from "@reelforge/render-core";
import { Badge, Button, Card, colors } from "@reelforge/ui-kit";

/**
 * Filtergraph Playground — configure a `RenderSpec` and see the exact FFmpeg
 * `-filter_complex` the renderer builds, live, from `@reelforge/render-core` (the
 * package is byte-identical to the Python executor `compose_ffmpeg.py`, so what
 * you see here is what the Celery worker runs). Read-only power-user reference;
 * nothing is submitted.
 */

const ASPECTS: Array<{ label: string; width: number; height: number }> = [
  { label: "9:16", width: 1080, height: 1920 },
  { label: "1:1", width: 1080, height: 1080 },
  { label: "16:9", width: 1920, height: 1080 },
];

export default function FiltergraphPage() {
  const [aspect, setAspect] = React.useState(0);
  const [fps, setFps] = React.useState(30);
  const [pip, setPip] = React.useState(true);
  const [caption, setCaption] = React.useState(true);
  const [narration, setNarration] = React.useState(true);
  const [bgm, setBgm] = React.useState(true);

  const { spec, graph, errors, outLabel, audio } = React.useMemo(() => {
    const a = ASPECTS[aspect] ?? ASPECTS[0]!;
    const opts: MakeSpecOptions = {
      width: a.width,
      height: a.height,
      fps,
      layout: pip ? "pip" : "captions_only",
      captionAss: caption ? "/tmp/captions.ass" : undefined,
      narration: narration ? 2 : undefined,
      bgm: narration && bgm ? 3 : undefined,
    };
    const spec = makeSpec(opts);
    return {
      spec,
      graph: buildFiltergraph(spec),
      errors: validateSpec(spec),
      outLabel: videoOutLabel(spec),
      audio: hasAudioOut(spec),
    };
  }, [aspect, fps, pip, caption, narration, bgm]);

  return (
    <main style={{ maxWidth: 900, margin: "0 auto", padding: 24, display: "grid", gap: 16, color: colors.textPrimary }}>
      <header style={{ display: "grid", gap: 4 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700 }}>Filtergraph Playground</h1>
        <p style={{ color: colors.muted, fontSize: 14 }}>
          Build a RenderSpec and inspect the exact FFmpeg <code>-filter_complex</code> the renderer
          composes — identical to the Python executor via <code>@reelforge/render-core</code>.
        </p>
      </header>

      <Card>
        <div style={{ display: "grid", gap: 14 }}>
          <Row label="Aspect">
            {ASPECTS.map((a, i) => (
              <Button key={a.label} variant={aspect === i ? "primary" : "secondary"} onClick={() => setAspect(i)}>
                {a.label}
              </Button>
            ))}
          </Row>
          <Row label="FPS">
            {[24, 30, 60].map((f) => (
              <Button key={f} variant={fps === f ? "primary" : "secondary"} onClick={() => setFps(f)}>
                {f}
              </Button>
            ))}
          </Row>
          <Row label="Layers">
            <Toggle on={pip} onClick={() => setPip((v) => !v)}>PiP avatar</Toggle>
            <Toggle on={caption} onClick={() => setCaption((v) => !v)}>Captions</Toggle>
            <Toggle on={narration} onClick={() => setNarration((v) => !v)}>Narration</Toggle>
            <Toggle on={narration && bgm} onClick={() => setBgm((v) => !v)}>BGM</Toggle>
          </Row>
        </div>
      </Card>

      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <Badge tone="accent">video out: {outLabel}</Badge>
        <Badge tone={audio ? "success" : "warning"}>{audio ? "has audio out" : "no audio"}</Badge>
        {errors.length ? <Badge tone="error">{errors.length} error{errors.length === 1 ? "" : "s"}</Badge> : <Badge tone="success">valid</Badge>}
      </div>

      {errors.length ? (
        <Card>
          <div style={{ display: "grid", gap: 4 }}>
            {errors.map((e, i) => (
              <div key={i} style={{ color: colors.error, fontSize: 13 }}>• {e}</div>
            ))}
          </div>
        </Card>
      ) : null}

      <Card>
        <div style={{ display: "grid", gap: 8 }}>
          <div style={{ fontSize: 13, color: colors.muted }}>-filter_complex</div>
          <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-all", fontSize: 12, color: colors.textPrimary, fontFamily: "ui-monospace, monospace" }}>
            {graph || "(empty — no filter nodes for this spec)"}
          </pre>
        </div>
      </Card>

      <Card>
        <div style={{ display: "grid", gap: 8 }}>
          <div style={{ fontSize: 13, color: colors.muted }}>RenderSpec</div>
          <pre style={{ margin: 0, whiteSpace: "pre-wrap", fontSize: 12, color: colors.textPrimary, fontFamily: "ui-monospace, monospace" }}>
            {JSON.stringify(spec, null, 2)}
          </pre>
        </div>
      </Card>
    </main>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
      <div style={{ width: 72, color: colors.muted, fontSize: 13 }}>{label}</div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>{children}</div>
    </div>
  );
}

function Toggle({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <Button variant={on ? "primary" : "ghost"} onClick={onClick}>
      {on ? <Check size={14} aria-hidden style={{ marginRight: 4, verticalAlign: "-2px" }} /> : null}
      {children}
    </Button>
  );
}
