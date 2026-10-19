/**
 * EarningsSummary — the top of the Earnings screen: the wallet balance (where
 * paid-out clips land) plus aggregate campaign spend. All money comes straight
 * from server-computed micros / `*_usd` strings; nothing is derived here beyond
 * the pure `summarizeSpend` reduction the screen passes in.
 */

import * as React from "react";
import { StyleSheet, Text, View } from "react-native";

import { colors } from "@/components/me/theme";
import { formatUsdMicros } from "@/lib/clipmarket";
import type { WalletBalance } from "@/lib/earnings";

import type { SpendSummary } from "../logic";

export interface EarningsSummaryProps {
  balance: WalletBalance | null;
  spend: SpendSummary;
}

export function EarningsSummary({ balance, spend }: EarningsSummaryProps) {
  return (
    <View style={styles.wrap}>
      <View style={styles.balanceCard} testID="earnings-balance">
        <Text style={styles.label}>Wallet balance</Text>
        <Text style={styles.big}>{balance ? balance.available_usd : "—"}</Text>
        <Text style={styles.sub}>
          {balance ? `${balance.reserved_usd} reserved` : "Loading balance…"}
        </Text>
      </View>

      <View style={styles.statsRow}>
        <Stat
          label="Campaign spend"
          value={formatUsdMicros(spend.totalSpentMicros)}
          testID="stat-spent"
        />
        <Stat
          label="Budget left"
          value={formatUsdMicros(spend.remainingMicros)}
          testID="stat-remaining"
        />
        <Stat
          label="Active"
          value={String(spend.activeCount)}
          testID="stat-active"
        />
      </View>
    </View>
  );
}

interface StatProps {
  label: string;
  value: string;
  testID: string;
}

function Stat({ label, value, testID }: StatProps) {
  return (
    <View style={styles.stat} testID={testID}>
      <Text style={styles.statValue}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 12 },
  balanceCard: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 14,
    padding: 18,
    gap: 4,
  },
  label: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  big: { color: colors.textPrimary, fontSize: 30, fontWeight: "800" },
  sub: { color: colors.muted, fontSize: 12 },
  statsRow: { flexDirection: "row", gap: 10 },
  stat: {
    flex: 1,
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    gap: 4,
  },
  statValue: { color: colors.textPrimary, fontSize: 16, fontWeight: "700" },
  statLabel: { color: colors.textSecondary, fontSize: 11 },
});
