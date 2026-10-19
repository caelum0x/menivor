/**
 * ActivityLedger — presentational wallet burn/credit ledger. Renders
 * `WalletActivityEntry[]` (newest first) from GET /wallet/activity: each row is
 * a credit (grant/refund/release, positive delta) or a burn (reserve/settle,
 * negative delta) with the running balance after it. Money is formatted with
 * `formatUsdMicros` only. Purely presentational.
 */

import { StyleSheet, Text, View } from "react-native";

import { colors } from "@/components/me/theme";
import {
  formatUsdMicros,
  type WalletActivityEntry,
} from "@/lib/marketplace";

/** Human labels for the ledger entry types the backend emits. */
const ENTRY_LABEL: Record<string, string> = {
  grant: "Credit added",
  reserve: "Reserved",
  settle: "Job charge",
  release: "Released",
  refund: "Refund",
  adjustment: "Adjustment",
};

export interface ActivityLedgerProps {
  rows: readonly WalletActivityEntry[];
  /** Message shown when there is no activity yet. */
  emptyLabel?: string;
}

export function ActivityLedger({
  rows,
  emptyLabel = "No wallet activity yet.",
}: Readonly<ActivityLedgerProps>) {
  if (rows.length === 0) {
    return <Text style={styles.empty}>{emptyLabel}</Text>;
  }

  return (
    <View>
      {rows.map((row, index) => {
        const positive = row.available_delta > 0;
        return (
          <View key={row.id ?? `row-${index}`} style={styles.row}>
            <View style={styles.left}>
              <Text style={styles.title}>
                {ENTRY_LABEL[row.entry_type] ?? row.entry_type}
              </Text>
              <Text style={styles.sub} numberOfLines={1}>
                {row.reason}
                {row.job_id ? ` · job ${row.job_id.slice(0, 8)}` : ""}
              </Text>
            </View>
            <View style={styles.right}>
              <Text style={[styles.amount, positive && styles.positive]}>
                {positive ? "+" : ""}
                {formatUsdMicros(row.available_delta)}
              </Text>
              <Text style={styles.bal}>bal {row.available_after_usd}</Text>
            </View>
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  empty: {
    color: colors.textSecondary,
    fontSize: 14,
    paddingVertical: 20,
    textAlign: "center",
  },
  row: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    gap: 12,
  },
  left: { flex: 1 },
  title: { color: colors.textPrimary, fontSize: 15, fontWeight: "500" },
  sub: { color: colors.textSecondary, fontSize: 12, marginTop: 2 },
  right: { alignItems: "flex-end" },
  amount: { color: colors.textPrimary, fontSize: 15, fontWeight: "600" },
  positive: { color: colors.success },
  bal: { color: colors.textSecondary, fontSize: 11, marginTop: 2 },
});
