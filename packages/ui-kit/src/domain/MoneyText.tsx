import * as React from "react";
import { colors } from "../tokens/index.js";
import { formatUsdMicros } from "../format/index.js";

/** Render integer microdollars as themed money text. */
export function MoneyText({ micros, muted }: { micros: number; muted?: boolean }) {
  return <span style={{ color: muted ? colors.textSecondary : colors.textPrimary, fontVariantNumeric: "tabular-nums" }}>{formatUsdMicros(micros)}</span>;
}
