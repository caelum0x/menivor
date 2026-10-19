import * as React from "react";
import { colors } from "../tokens/index.js";
export function Divider({ vertical }: { vertical?: boolean }) {
  return <div style={vertical
    ? { width: 1, alignSelf: "stretch", background: colors.border }
    : { height: 1, width: "100%", background: colors.border }} />;
}
