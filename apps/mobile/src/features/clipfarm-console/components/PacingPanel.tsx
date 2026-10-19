/**
 * PacingPanel — presentational pacing snapshot for one channel. Shows the count
 * of COMPLETE-but-unpublished clips ready to pace onto the calendar plus the
 * per-account clips-rendered-today budget. Purely presentational: the parent
 * screen owns the `ChannelPacing` data and the "Schedule now" action.
 */

import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors } from "@/components/me/theme";
import type { ChannelPacing } from "@/lib/series";

import { totalRenderedToday } from "../logic";

export interface PacingPanelProps {
  pacing: ChannelPacing | null;
  /** When set, renders a "Schedule now" button that invokes this. */
  onSchedule?: () => void;
  scheduling?: boolean;
}

export function PacingPanel({
  pacing,
  onSchedule,
  scheduling = false,
}: Readonly<PacingPanelProps>) {
  const pending = pacing?.pending ?? [];
  const rendered = pacing?.rendered_today ?? {};
  const accounts = Object.keys(rendered).sort();
  const renderedToday = totalRenderedToday(rendered);

  return (
    <View style={styles.wrap}>
      <View style={styles.cards}>
        <View style={styles.card}>
          <Text style={styles.label}>Pending publish</Text>
          <Text style={styles.value} testID="pending-count">
            {pending.length}
          </Text>
        </View>
        <View style={styles.card}>
          <Text style={styles.label}>Rendered today</Text>
          <Text style={styles.value} testID="rendered-today">
            {renderedToday}
          </Text>
        </View>
      </View>

      {accounts.length > 0 ? (
        <View style={styles.accounts}>
          {accounts.map((account) => (
            <View key={account} style={styles.accountRow}>
              <Text style={styles.accountName} numberOfLines={1}>
                {account || "(default)"}
              </Text>
              <Text style={styles.accountCount}>{rendered[account]}</Text>
            </View>
          ))}
        </View>
      ) : (
        <Text style={styles.empty}>No clips rendered today yet.</Text>
      )}

      {onSchedule ? (
        <Pressable
          style={[styles.action, scheduling && styles.actionDisabled]}
          onPress={onSchedule}
          disabled={scheduling || pending.length === 0}
          accessibilityRole="button"
          accessibilityLabel="Pace pending clips onto the publish calendar"
          testID="schedule-button"
        >
          <Text style={styles.actionText}>
            {scheduling ? "Scheduling…" : "Schedule pending"}
          </Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 12 },
  cards: { flexDirection: "row", gap: 12 },
  card: {
    flex: 1,
    backgroundColor: colors.card,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 16,
  },
  label: { color: colors.textSecondary, fontSize: 13 },
  value: {
    color: colors.textPrimary,
    fontSize: 26,
    fontWeight: "700",
    marginTop: 6,
  },
  accounts: {
    backgroundColor: colors.cardAlt,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: 14,
    paddingVertical: 6,
  },
  accountRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingVertical: 8,
  },
  accountName: { color: colors.textSecondary, fontSize: 14, flex: 1 },
  accountCount: { color: colors.textPrimary, fontSize: 14, fontWeight: "700" },
  empty: { color: colors.muted, fontSize: 13 },
  action: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
  },
  actionDisabled: { opacity: 0.6 },
  actionText: { color: "#fff", fontSize: 15, fontWeight: "600" },
});
