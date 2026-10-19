import * as React from "react";
import { colors, radii, spacing, fontWeights } from "../tokens/index.js";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

// A type intersection (not `interface extends`) so the emitted `.d.ts` resolves
// cleanly when consumed cross-package (matches how Card's inline props resolve).
export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  loading?: boolean;
};

const BG: Record<ButtonVariant, string> = {
  primary: colors.primary,
  secondary: colors.surfaceAlt,
  ghost: "transparent",
  danger: colors.error,
};

/** Themed button (primary/secondary/ghost/danger) with a loading state. */
export function Button({ variant = "primary", loading, disabled, children, style, ...rest }: ButtonProps) {
  return (
    <button
      disabled={disabled || loading}
      style={{
        background: BG[variant],
        color: variant === "primary" || variant === "danger" ? colors.bg : colors.textPrimary,
        border: variant === "ghost" ? `1px solid ${colors.border}` : "none",
        borderRadius: radii.md,
        padding: `${spacing.sm}px ${spacing.lg}px`,
        fontWeight: fontWeights.medium,
        opacity: disabled || loading ? 0.5 : 1,
        cursor: disabled || loading ? "not-allowed" : "pointer",
        ...style,
      }}
      {...rest}
    >
      {loading ? "…" : children}
    </button>
  );
}
