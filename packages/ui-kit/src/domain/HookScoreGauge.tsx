import * as React from "react";
import { hookScore, GATE, type HookSignals } from "@reelforge/growth-analytics";
import { colors } from "../tokens/index.js";

/**
 * 0–100 hook-strength gauge vs the 70% gate — reuses `growth-analytics.hookScore`
 * so the client shows the exact number the backend gates on.
 */
export function HookScoreGauge({ signals }: { signals: HookSignals }) {
  const { score, passes } = hookScore(signals);
  const pct = Math.round(score * 100);
  const tone = passes ? colors.success : colors.error;
  return (
    <div>
      <div style={{ color: tone, fontSize: 28, fontWeight: 800 }}>{pct}</div>
      <div style={{ color: colors.muted, fontSize: 12 }}>
        hook score · gate {Math.round(GATE * 100)}% · {passes ? "passes" : "below gate"}
      </div>
    </div>
  );
}
