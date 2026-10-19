/** Shared card styles for the winner loop detail sections. */

import { StyleSheet } from "react-native";

import { colors, radius, spacing, typeScale } from "@/src/shared/theme";

export const sectionStyles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    gap: spacing.sm,
  },
  head: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  title: { color: colors.textPrimary, fontSize: typeScale.subheading, fontWeight: "700", flex: 1 },
  body: { color: colors.textPrimary, fontSize: typeScale.caption, lineHeight: 19 },
  strong: { color: colors.textPrimary, fontSize: typeScale.body, fontWeight: "700", lineHeight: 21 },
  muted: { color: colors.textSecondary, fontSize: typeScale.caption, lineHeight: 19 },
  micro: { color: colors.textSecondary, fontSize: typeScale.micro, lineHeight: 16 },
  label: { color: colors.textPrimary, fontSize: typeScale.caption, fontWeight: "700" },
  link: { color: colors.accent, fontSize: typeScale.caption, fontWeight: "700" },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm, flexWrap: "wrap" },
});
