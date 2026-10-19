"use client";

import * as React from "react";
import { X } from "lucide-react";
import { selectWinner, type Variant } from "@reelforge/growth-analytics";
import { Badge, Button, Card, colors } from "@reelforge/ui-kit";

/**
 * A/B Winner Lab — an interactive tool over `@reelforge/growth-analytics.selectWinner`,
 * the retention-weighted variant picker (byte-identical to `ab.py`) the pipeline
 * uses to promote the best cut: `score = 0.6·completion + 0.4·(avg_watch / max)`.
 * Edit the variants' completion + avg-watch and watch the scores and the winner
 * update live. Read-only reference; nothing is submitted.
 */

interface Row {
  id: string;
  completion: number;
  avg_watch: number;
}

let nextId = 4;

export default function AbLabPage() {
  const [rows, setRows] = React.useState<Row[]>([
    { id: "A", completion: 0.55, avg_watch: 12 },
    { id: "B", completion: 0.42, avg_watch: 18 },
    { id: "C", completion: 0.6, avg_watch: 9 },
  ]);

  const result = React.useMemo(
    () => selectWinner(rows.map<Variant>((r) => ({ id: r.id, completion: r.completion, avg_watch: r.avg_watch }))),
    [rows],
  );

  const patch = (id: string, key: "completion" | "avg_watch", value: number) =>
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, [key]: value } : r)));

  const addRow = () =>
    setRows((prev) => [...prev, { id: String.fromCharCode(64 + ++nextId), completion: 0.5, avg_watch: 10 }]);

  const removeRow = (id: string) => setRows((prev) => (prev.length <= 2 ? prev : prev.filter((r) => r.id !== id)));

  // Rank for display: highest score first.
  const ranked = [...rows].sort((a, b) => (result.scores[b.id] ?? 0) - (result.scores[a.id] ?? 0));

  return (
    <main style={{ maxWidth: 720, margin: "0 auto", padding: 24, display: "grid", gap: 16, color: colors.textPrimary }}>
      <header style={{ display: "grid", gap: 4 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700 }}>A/B Winner Lab</h1>
        <p style={{ color: colors.muted, fontSize: 14 }}>
          The retention-weighted variant picker the pipeline promotes with — identical to the renderer via{" "}
          <code>@reelforge/growth-analytics</code>. Score = 0.6·completion + 0.4·(avg_watch ÷ best).
        </p>
      </header>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ fontSize: 14 }}>
          Winner:{" "}
          {result.winner ? (
            <Badge tone="success">Variant {result.winner}</Badge>
          ) : (
            <span style={{ color: colors.muted }}>—</span>
          )}
        </div>
        <Button variant="secondary" onClick={addRow}>+ Add variant</Button>
      </div>

      {ranked.map((r) => {
        const score = result.scores[r.id] ?? 0;
        const isWinner = r.id === result.winner;
        return (
          <Card key={r.id}>
            <div style={{ display: "grid", gap: 12 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <div style={{ fontWeight: 700 }}>Variant {r.id}</div>
                  {isWinner ? <Badge tone="success">winner</Badge> : null}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <div style={{ fontSize: 20, fontWeight: 700, color: isWinner ? colors.success : colors.textPrimary }}>
                    {Math.round(score * 100)}%
                  </div>
                  <Button variant="ghost" onClick={() => removeRow(r.id)} disabled={rows.length <= 2} aria-label={`Remove variant ${r.id}`}>
                    <X size={16} aria-hidden />
                  </Button>
                </div>
              </div>

              <Slider label="Completion" value={r.completion} min={0} max={1} step={0.01}
                fmt={(v) => `${Math.round(v * 100)}%`} onChange={(v) => patch(r.id, "completion", v)} />
              <Slider label="Avg watch (s)" value={r.avg_watch} min={0} max={60} step={1}
                fmt={(v) => `${v.toFixed(0)}s`} onChange={(v) => patch(r.id, "avg_watch", v)} />

              <div style={{ height: 6, borderRadius: 3, background: colors.surfaceAlt }}>
                <div style={{ width: `${Math.min(100, score * 100)}%`, height: "100%", borderRadius: 3, background: isWinner ? colors.success : colors.primary }} />
              </div>
            </div>
          </Card>
        );
      })}
    </main>
  );
}

function Slider({ label, value, min, max, step, fmt, onChange }: {
  label: string; value: number; min: number; max: number; step: number;
  fmt: (v: number) => string; onChange: (v: number) => void;
}) {
  return (
    <div style={{ display: "grid", gap: 4 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
        <span style={{ color: colors.muted }}>{label}</span>
        <span>{fmt(value)}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(Number(e.target.value))} aria-label={label}
        style={{ width: "100%", accentColor: colors.primary }} />
    </div>
  );
}
