import * as React from "react";
import { colors, radii } from "../tokens/index.js";

export interface Slot { role: string; t_start_ms: number; t_end_ms: number; }

const ROLE_COLOR: Record<string, string> = {
  hook: "#ff6b6b", setup: "#8b7bff", rising: "#6a5bff", climax: "#fbbf24",
  payoff: "#4ade80", cta: "#25f4ee", loop: "#c9c9d6",
};

/** Hook / Proof / Payoff / Loop timeline bar for a shot-template's slots. */
export function SegmentSlotBar({ slots }: { slots: Slot[] }) {
  const total = slots.reduce((m, s) => Math.max(m, s.t_end_ms), 0) || 1;
  return (
    <div style={{ display: "flex", height: 28, borderRadius: radii.sm, overflow: "hidden", background: colors.surfaceAlt }}>
      {slots.map((s, i) => {
        const w = ((s.t_end_ms - s.t_start_ms) / total) * 100;
        return (
          <div key={i} title={s.role} style={{ width: `${w}%`, background: ROLE_COLOR[s.role] ?? colors.muted,
            display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, color: colors.bg, fontWeight: 700 }}>
            {w > 8 ? s.role : ""}
          </div>
        );
      })}
    </div>
  );
}
