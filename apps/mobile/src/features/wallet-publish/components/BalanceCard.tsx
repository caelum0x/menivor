/**
 * BalanceCard — presentational wallet balance summary. Renders the caller's
 * available + reserved USD, formatted from integer microdollars with
 * `formatUsdMicros` (display only; never derived here). Purely presentational:
 * all data + the optional "Top up" action are owned by the parent screen.
 */

import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors } from "@/components/me/theme";
import { formatUsdMicros, type WalletBalance } from "@/lib/marketplace";

export interface BalanceCardProps {
  balance: WalletBalance | null;
  /** When set, renders a "Top up" button that invokes this. */
  onTopUp?: () => void;
}

export function BalanceCard({ balance, onTopUp }: Readonly<BalanceCardProps>) {
  return (
    <View style={styles.wrap}>
      <View style={styles.cards}>
        <View style={styles.card}>
          <Text style={styles.label}>Available</Text>
          <Text style={styles.value}>
            {formatUsdMicros(balance?.available_micros)}
          </Text>
        </View>
        <View style={styles.card}>
          <Text style={styles.label}>Reserved</Text>
          <Text style={styles.value}>
            {formatUsdMicros(balance?.reserved_micros)}
          </Text>
        </View>
      </View>
      {onTopUp ? (
        <Pressable
          style={styles.topUp}
          onPress={onTopUp}
          accessibilityRole="button"
          accessibilityLabel="Add wallet credit"
        >
          <Text style={styles.topUpText}>Top up</Text>
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
  topUp: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
  },
  topUpText: { color: "#fff", fontSize: 15, fontWeight: "600" },
});
