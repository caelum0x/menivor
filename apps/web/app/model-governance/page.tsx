"use client";

import * as React from "react";
import {
  DEPRECATION_REGISTRY,
  LICENSE_REGISTRY,
  canUseForPaid,
  licenseClass,
  migrate,
  type LicenseClass,
  type Lifecycle,
} from "@reelforge/provider-adapter-kit";
import { Badge, Card, colors } from "@reelforge/ui-kit";

/**
 * Model Governance — the license-class + lifecycle gates from
 * `@reelforge/provider-adapter-kit` (byte-identical to the Python `license.py`/
 * `deprecation.py`), applied to every catalogued model: can it back a *paid*
 * render (commercial-safe only), and is it active / deprecating / sunset as of a
 * chosen date? Move the date forward to see which models sunset when. Read-only.
 */

const LICENSE_TONE: Record<LicenseClass, "success" | "warning" | "error"> = {
  "commercial-safe": "success",
  territorial: "warning",
  "non-commercial": "error",
};

const LIFECYCLE_TONE: Record<Lifecycle, "success" | "warning" | "error"> = {
  active: "success",
  deprecating: "warning",
  sunset: "error",
};

/** Every model mentioned by either registry, sorted. */
const MODELS = Array.from(
  new Set([...Object.keys(LICENSE_REGISTRY), ...Object.keys(DEPRECATION_REGISTRY)]),
).sort();

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function ModelGovernancePage() {
  const [today, setToday] = React.useState(todayISO());

  const rows = React.useMemo(
    () =>
      MODELS.map((model) => ({
        model,
        klass: licenseClass(model),
        paid: canUseForPaid(model),
        hint: migrate(model, today),
      })),
    [today],
  );

  const paidSafe = rows.filter((r) => r.paid).length;
  const migrating = rows.filter((r) => r.hint.should_migrate).length;

  return (
    <main style={{ maxWidth: 820, margin: "0 auto", padding: 24, display: "grid", gap: 16, color: colors.textPrimary }}>
      <header style={{ display: "grid", gap: 4 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700 }}>Model Governance</h1>
        <p style={{ color: colors.muted, fontSize: 14 }}>
          License-class and lifecycle gates from <code>@reelforge/provider-adapter-kit</code> — the same
          rules the gateway enforces before a model backs a paid render.
        </p>
      </header>

      <Card>
        <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
            <span style={{ color: colors.muted }}>As of</span>
            <input type="date" value={today} onChange={(e) => setToday(e.target.value || todayISO())}
              style={{ background: colors.surfaceAlt, color: colors.textPrimary, border: `1px solid ${colors.border}`, borderRadius: 8, padding: "6px 10px", fontSize: 13 }} />
          </label>
          <Badge tone="success">{paidSafe}/{rows.length} paid-safe</Badge>
          <Badge tone={migrating ? "warning" : "success"}>{migrating} need migration</Badge>
        </div>
      </Card>

      <Card>
        <div style={{ display: "grid", gap: 8 }}>
          <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1.4fr", gap: 8, fontSize: 12, color: colors.muted, paddingBottom: 6, borderBottom: `1px solid ${colors.border}` }}>
            <span>model</span><span>license</span><span>lifecycle</span><span>paid / migrate&nbsp;→</span>
          </div>
          {rows.map((r) => (
            <div key={r.model} style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1.4fr", gap: 8, alignItems: "center", fontSize: 13 }}>
              <span style={{ fontFamily: "ui-monospace, monospace", fontSize: 12 }}>{r.model}</span>
              <span><Badge tone={LICENSE_TONE[r.klass]}>{r.klass}</Badge></span>
              <span><Badge tone={LIFECYCLE_TONE[r.hint.status]}>{r.hint.status}</Badge></span>
              <span style={{ fontSize: 12, color: colors.muted }}>
                {r.paid ? "paid-safe" : "not paid-safe"}
                {r.hint.should_migrate && r.hint.replacement ? ` · → ${r.hint.replacement}` : ""}
              </span>
            </div>
          ))}
        </div>
      </Card>

      <div style={{ fontSize: 12, color: colors.muted }}>
        Only <strong>commercial-safe</strong> models may back a paid render; <strong>territorial</strong> and{" "}
        <strong>non-commercial</strong> are gated. Unknown models default to <strong>territorial</strong> (gate-before-use).
      </div>
    </main>
  );
}
