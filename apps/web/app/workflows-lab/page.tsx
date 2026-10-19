"use client";

import * as React from "react";
import {
  getWorkflow,
  graphHash,
  listWorkflows,
  validateInputs,
  type InputSlot,
} from "@reelforge/comfy-workflow-schema";
import { Badge, Card, colors } from "@reelforge/ui-kit";

/**
 * Workflows Lab — inspect the first-party ComfyUI workflow descriptors from
 * `@reelforge/comfy-workflow-schema` (byte-identical to the Python `catalog.py`/
 * `pin.py`): the deterministic `graphHash` pin, pinned custom-node commits, weight
 * refs, and the input contract. Fill the typed inputs and run the real
 * `validateInputs` to see the exact errors the API would return. This is the
 * client view of the §6 "workflow manifest" the external registry requires.
 */

function defaultValue(slot: InputSlot): unknown {
  if (slot.type === "int") return slot.default ?? slot.min ?? 0;
  if (slot.type === "string") return slot.default ?? "";
  return undefined; // image/video/audio: represented by a "provided" toggle
}

export default function WorkflowsLabPage() {
  const slugs = React.useMemo(() => listWorkflows(), []);
  const [slug, setSlug] = React.useState(slugs[0] ?? "wan-i2v");
  const wf = React.useMemo(() => getWorkflow(slug), [slug]);

  const [values, setValues] = React.useState<Record<string, unknown>>({});
  // Reset the value map whenever the workflow changes.
  React.useEffect(() => {
    const seed: Record<string, unknown> = {};
    for (const s of wf.inputs) {
      const v = defaultValue(s);
      if (v !== undefined) seed[s.name] = v;
    }
    setValues(seed);
  }, [wf]);

  const errors = React.useMemo(() => validateInputs(wf, values), [wf, values]);
  const pin = React.useMemo(() => graphHash(wf), [wf]);

  const setVal = (name: string, v: unknown) => setValues((prev) => ({ ...prev, [name]: v }));

  return (
    <main style={{ maxWidth: 760, margin: "0 auto", padding: 24, display: "grid", gap: 16, color: colors.textPrimary }}>
      <header style={{ display: "grid", gap: 4 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700 }}>Workflows Lab</h1>
        <p style={{ color: colors.muted, fontSize: 14 }}>
          First-party ComfyUI workflow descriptors + the deterministic graph pin, from the real{" "}
          <code>@reelforge/comfy-workflow-schema</code>. Fill inputs to run the actual validator.
        </p>
      </header>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {slugs.map((sName) => (
          <button
            key={sName}
            onClick={() => setSlug(sName)}
            style={{
              borderRadius: 10, padding: "8px 12px", fontSize: 13, fontWeight: 600, cursor: "pointer",
              border: `1px solid ${slug === sName ? colors.primary : colors.border}`,
              background: slug === sName ? colors.primary : "transparent",
              color: slug === sName ? colors.bg : colors.textPrimary,
            }}
          >
            {sName}
          </button>
        ))}
      </div>

      <Card>
        <div style={{ display: "grid", gap: 10 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
            <div style={{ fontWeight: 700 }}>{wf.slug}</div>
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <Badge tone="accent">{wf.category}</Badge>
              <span style={{ fontFamily: "ui-monospace, monospace", fontSize: 12, color: colors.muted }}>pin {pin}</span>
            </div>
          </div>
          <div style={{ color: colors.textSecondary, fontSize: 14 }}>{wf.description}</div>

          <div style={{ fontSize: 12, color: colors.muted, marginTop: 4 }}>pinned node commits</div>
          <div style={{ display: "grid", gap: 4 }}>
            {Object.entries(wf.node_commits).map(([name, commit]) => (
              <div key={name} style={{ display: "flex", justifyContent: "space-between", fontFamily: "ui-monospace, monospace", fontSize: 12 }}>
                <span style={{ color: colors.textSecondary }}>{name}</span>
                <span>{commit}</span>
              </div>
            ))}
          </div>

          <div style={{ fontSize: 12, color: colors.muted, marginTop: 4 }}>weight refs</div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {wf.weight_refs.map((w) => (
              <Badge key={w}>{w}</Badge>
            ))}
          </div>
        </div>
      </Card>

      <Card>
        <div style={{ display: "grid", gap: 12 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div style={{ fontWeight: 600 }}>Input contract</div>
            <Badge tone={errors.length ? "error" : "success"}>{errors.length ? `${errors.length} error${errors.length === 1 ? "" : "s"}` : "valid"}</Badge>
          </div>

          {wf.inputs.map((slot) => (
            <div key={slot.name} style={{ display: "grid", gap: 4 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                <span>
                  {slot.name} <span style={{ color: colors.muted }}>: {slot.type}{slot.required ? " *" : ""}</span>
                </span>
                {slot.type === "int" && (slot.min !== undefined || slot.max !== undefined) ? (
                  <span style={{ color: colors.muted, fontSize: 12 }}>[{slot.min ?? "−∞"}, {slot.max ?? "∞"}]</span>
                ) : null}
              </div>
              {slot.type === "int" ? (
                <input type="number" value={Number(values[slot.name] ?? 0)} onChange={(e) => setVal(slot.name, Number(e.target.value))}
                  style={inputStyle} />
              ) : slot.type === "string" ? (
                <input type="text" value={String(values[slot.name] ?? "")} onChange={(e) => setVal(slot.name, e.target.value)}
                  placeholder={slot.required ? "required" : "optional"} style={inputStyle} />
              ) : (
                <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13, color: colors.textSecondary }}>
                  <input type="checkbox" checked={Object.prototype.hasOwnProperty.call(values, slot.name)}
                    onChange={(e) => setValues((prev) => {
                      const next = { ...prev };
                      if (e.target.checked) next[slot.name] = `${slot.type}-asset`;
                      else delete next[slot.name];
                      return next;
                    })} />
                  {slot.type} provided
                </label>
              )}
            </div>
          ))}

          {errors.length ? (
            <div style={{ display: "grid", gap: 4 }}>
              {errors.map((e, i) => (
                <div key={i} style={{ color: colors.error, fontSize: 13 }}>• {e}</div>
              ))}
            </div>
          ) : (
            <div style={{ color: colors.success, fontSize: 13 }}>All inputs satisfy the contract.</div>
          )}
        </div>
      </Card>
    </main>
  );
}

const inputStyle: React.CSSProperties = {
  background: colors.surfaceAlt,
  color: colors.textPrimary,
  border: `1px solid ${colors.border}`,
  borderRadius: 8,
  padding: "8px 10px",
  fontSize: 13,
};
