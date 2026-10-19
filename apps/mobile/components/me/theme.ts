/**
 * Legacy color map kept for the ~150 screens that import `colors` from here.
 *
 * It now re-exports the shared editorial tokens (src/shared/theme) so a single
 * palette change flows to every screen. The key names are preserved for
 * backwards compatibility; the values are the ink/paper/#E6C76A editorial
 * system. `primary` and `accent` are the single #E6C76A signal color — place
 * dark type (`colors.bg`) on top of them, never white.
 */

import { colors as tokens } from "@/src/shared/theme";

export const colors = {
  bg: tokens.bg,
  card: tokens.surface,
  cardAlt: tokens.surfaceAlt,
  border: tokens.border,
  primary: tokens.accent,
  accent: tokens.accent,
  textPrimary: tokens.textPrimary,
  textSecondary: tokens.textSecondary,
  muted: tokens.textFaint,
  success: tokens.success,
  error: tokens.danger,
} as const;
