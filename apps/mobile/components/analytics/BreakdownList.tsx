/**
 * A usage breakdown as a labelled bar list: each row shows a key (layout /
 * language / variant count / hook), its job count, and a horizontal bar sized
 * relative to the largest row. Rows are sorted descending by count.
 */

import { StyleSheet, Text, View } from "react-native";

import { colors } from "@/components/me/theme";
import type { AnalyticsBreakdownItem } from "@/lib/types";

import { Bar } from "./Bar";
import { formatCount, toPercent } from "./format";

interface BreakdownListProps {
  items: AnalyticsBreakdownItem[];
  /** Bar colour (defaults to accent). */
  color?: string;
  /** Cap the number of rows shown (top-N by count). */
  limit?: number;
  emptyLabel?: string;
}

export function BreakdownList({
  items,
  color,
  limit,
  emptyLabel = "No data in this window yet.",
}: BreakdownListProps) {
  const sorted = [...items].sort((a, b) => b.count - a.count);
  const rows = typeof limit === "number" ? sorted.slice(0, limit) : sorted;
  const max = rows.reduce((acc, r) => Math.max(acc, r.count), 0);

  if (rows.length === 0) {
    return (
      <View style={styles.card}>
        <Text style={styles.empty}>{emptyLabel}</Text>
      </View>
    );
  }

  return (
    <View style={styles.card}>
      {rows.map((row, index) => (
        <View key={`${row.key}-${index}`} style={styles.row}>
          <View style={styles.rowHeader}>
            <Text style={styles.rowLabel} numberOfLines={1}>
              {row.label ?? row.key}
            </Text>
            <Text style={styles.rowCount}>{formatCount(row.count)}</Text>
          </View>
          <Bar percent={toPercent(row.count, max)} color={color} height={8} />
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 14,
  },
  row: { gap: 6 },
  rowHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
  },
  rowLabel: { color: colors.textSecondary, fontSize: 14, flex: 1 },
  rowCount: { color: colors.textPrimary, fontSize: 14, fontWeight: "700" },
  empty: { color: colors.muted, fontSize: 13, paddingVertical: 6 },
});
