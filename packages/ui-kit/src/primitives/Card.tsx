import * as React from "react";
import { colors, radii, spacing } from "../tokens/index.js";

/** Surface card. */
export function Card({ children, style, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      style={{ background: colors.surface, border: `1px solid ${colors.border}`,
        borderRadius: radii.lg, padding: spacing.lg, ...style }}
      {...rest}
    >
      {children}
    </div>
  );
}
