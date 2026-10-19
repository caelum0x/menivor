/**
 * Shared editorial styles for the approvals and channel-publishing screens
 * (cards, chips, buttons, inputs, notes). Tokens only; no one-off colors.
 */

import { StyleSheet } from "react-native";

import { colors } from "@/components/me/theme";
import { radius, spacing, typeScale, weight } from "@/src/shared/theme";

export const ui = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.xl - 4, paddingBottom: 48, gap: spacing.md },
  intro: { color: colors.textSecondary, fontSize: typeScale.body, lineHeight: 22 },
  sectionTitle: {
    color: colors.textPrimary,
    fontSize: typeScale.subheading,
    fontWeight: weight.bold,
    marginTop: spacing.md,
  },
  kicker: {
    color: colors.textSecondary,
    fontSize: typeScale.micro,
    fontWeight: weight.bold,
    letterSpacing: 0.8,
    textTransform: "uppercase",
  },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.md,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  row: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: spacing.sm },
  title: { color: colors.textPrimary, fontSize: typeScale.subheading, fontWeight: weight.semibold },
  body: { color: colors.textSecondary, fontSize: typeScale.body, lineHeight: 21 },
  muted: { color: colors.muted, fontSize: typeScale.caption, lineHeight: 18 },
  error: { color: colors.error, fontSize: typeScale.caption, lineHeight: 18 },
  ok: { color: colors.success, fontSize: typeScale.caption, lineHeight: 18 },
  badge: {
    borderColor: colors.border,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
  },
  badgeText: { color: colors.textSecondary, fontSize: typeScale.micro, fontWeight: weight.semibold },
  badgeDanger: { borderColor: colors.error },
  badgeDangerText: { color: colors.error },
  badgeOk: { borderColor: colors.success },
  badgeOkText: { color: colors.success },
  chip: {
    borderColor: colors.border,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
    backgroundColor: colors.cardAlt,
  },
  chipOn: { backgroundColor: colors.accent, borderColor: colors.accent },
  chipText: { color: colors.textSecondary, fontSize: typeScale.caption, fontWeight: weight.semibold },
  chipTextOn: { color: colors.bg },
  input: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.md,
    color: colors.textPrimary,
    fontSize: typeScale.body,
    paddingHorizontal: spacing.md,
    paddingVertical: 10,
  },
  multiline: { minHeight: 96, textAlignVertical: "top" },
  button: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: 10,
    backgroundColor: colors.accent,
  },
  buttonText: { color: colors.bg, fontSize: typeScale.caption, fontWeight: weight.bold },
  buttonGhost: {
    backgroundColor: "transparent",
    borderColor: colors.border,
    borderWidth: StyleSheet.hairlineWidth,
  },
  buttonGhostText: { color: colors.textPrimary },
  disabled: { opacity: 0.45 },
  center: { alignItems: "center", justifyContent: "center", paddingVertical: 40, gap: spacing.sm },
  empty: {
    borderColor: colors.border,
    borderWidth: StyleSheet.hairlineWidth,
    borderStyle: "dashed",
    borderRadius: radius.md,
    padding: spacing.lg,
  },
});
