import * as React from "react";
import { colors } from "../tokens/index.js";
export function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button role="switch" aria-checked={checked} onClick={() => onChange(!checked)}
      style={{ width: 44, height: 26, borderRadius: 999, border: "none", cursor: "pointer",
        background: checked ? colors.primary : colors.surfaceAlt, position: "relative", transition: "background .15s" }}>
      <span style={{ position: "absolute", top: 3, left: checked ? 21 : 3, width: 20, height: 20,
        borderRadius: 999, background: "#fff", transition: "left .15s" }} />
    </button>
  );
}
