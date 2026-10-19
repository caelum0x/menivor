/**
 * ActivityRow — one wallet ledger entry on the Earnings screen. Renders the
 * server-formatted running balance and a signed delta (credits from paid-out
 * clips show green). Presentational only.
 */

import * as React from "react";
import { StyleSheet, Text, View } from "react-native";

import { colors } from "@/components/me/theme";
import { formatUsdMicros } from "@/lib/clipmarket";
import type { WalletActivityEntry } from "@/lib/earnings";

export interface ActivityRowProps {
  entry: WalletActivityEntry;
}

export function ActivityRow({ entry }: ActivityRowProps) {
  const isCredit = entry.available_delta > 0;
  const sign = isCredit ? "+" : "";
  const deltaColor = isCredit ? colors.success : colors.textPrimary;

  return (
    <View style={styles.row} testID={`activity-${entry.id ?? "na"}`}>
      <View style={styles.left}>
        <Text style={styles.reason} numberOfLines={1}>
          {entry.reason || entry.entry_type}
        </Text>
        <Text style={styles.after}>Balance {entry.available_after_usd}</Text>
      </View>
      <Text style={[styles.delta, { color: deltaColor }]}>
        {sign}
        {formatUsdMicros(entry.available_delta)}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 12,
    borderBottomColor: colors.border,
    borderBottomWidth: StyleSheet.hairlineWidth,
    gap: 12,
  },
  left: { flexShrink: 1, gap: 2 },
  reason: { color: colors.textPrimary, fontSize: 14, fontWeight: "600" },
  after: { color: colors.muted, fontSize: 12 },
  delta: { fontSize: 15, fontWeight: "700" },
});
