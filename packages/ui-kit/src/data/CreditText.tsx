import * as React from "react";
import { colors } from "../tokens/index.js";
import { formatCredits } from "../format/index.js";
export function CreditText({ micros }: { micros: number }) {
  return <span style={{ color: colors.accent, fontVariantNumeric: "tabular-nums" }}>{formatCredits(micros)}</span>;
}
