import * as React from "react";
import { colors, radii, spacing } from "../tokens/index.js";
export interface TextAreaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> { label?: string; }
export function TextArea({ label, style, ...rest }: TextAreaProps) {
  return (
    <label style={{ display: "block" }}>
      {label ? <span style={{ display: "block", color: colors.textPrimary, fontSize: 13, fontWeight: 600, marginBottom: 6 }}>{label}</span> : null}
      <textarea style={{ width: "100%", minHeight: 88, background: colors.surface, color: colors.textPrimary,
        border: `1px solid ${colors.border}`, borderRadius: radii.md, padding: spacing.md, fontSize: 14,
        resize: "vertical", ...style }} {...rest} />
    </label>
  );
}
