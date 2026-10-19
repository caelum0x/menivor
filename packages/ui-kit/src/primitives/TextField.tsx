import * as React from "react";
import { colors, radii, spacing } from "../tokens/index.js";
export interface TextFieldProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string; error?: string;
}
export function TextField({ label, error, style, ...rest }: TextFieldProps) {
  return (
    <label style={{ display: "block" }}>
      {label ? <span style={{ display: "block", color: colors.textPrimary, fontSize: 13, fontWeight: 600, marginBottom: 6 }}>{label}</span> : null}
      <input style={{ width: "100%", background: colors.surface, color: colors.textPrimary,
        border: `1px solid ${error ? colors.error : colors.border}`, borderRadius: radii.md,
        padding: `${spacing.sm}px ${spacing.md}px`, fontSize: 14, ...style }} {...rest} />
      {error ? <span style={{ color: colors.error, fontSize: 12 }}>{error}</span> : null}
    </label>
  );
}
