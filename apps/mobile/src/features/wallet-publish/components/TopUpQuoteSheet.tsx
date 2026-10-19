/**
 * TopUpQuoteSheet — presentational breakdown of a server-authoritative wallet
 * top-up quote (POST /wallet/purchase-quotes). Shows credit + fee + tax +
 * processor and the server-computed total. Every figure comes straight from the
 * {@link PurchaseQuote}; no arithmetic happens here (no local money math).
 * Money is formatted with `formatUsdMicros` only. The Confirm action + its
 * busy/disabled state are owned by the parent screen.
 */

import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import { colors } from "@/components/me/theme";
import { formatUsdMicros } from "@/lib/marketplace";
import type { PurchaseQuote } from "@/lib/wallet";

export interface TopUpQuoteSheetProps {
  quote: PurchaseQuote;
  /** True while a checkout request is in flight. */
  submitting: boolean;
  onConfirm: () => void;
  onDismiss: () => void;
}

interface Line {
  label: string;
  micros: number;
  strong?: boolean;
}

export function TopUpQuoteSheet({
  quote,
  submitting,
  onConfirm,
  onDismiss,
}: Readonly<TopUpQuoteSheetProps>) {
  // Display-only projection of the server figures — never recomputed.
  const lines: readonly Line[] = [
    { label: "Wallet credit", micros: quote.credit_micros },
    { label: "Processing fee", micros: quote.fee_micros },
    { label: "Tax", micros: quote.tax_micros },
    { label: "Total charge", micros: quote.total_charge_micros, strong: true },
  ];

  return (
    <View style={styles.sheet}>
      <Text style={styles.title}>Confirm top-up</Text>
      {lines.map((line) => (
        <View key={line.label} style={styles.line}>
          <Text style={[styles.lineLabel, line.strong && styles.strong]}>
            {line.label}
          </Text>
          <Text style={[styles.lineValue, line.strong && styles.strong]}>
            {formatUsdMicros(line.micros)}
          </Text>
        </View>
      ))}
      <Text style={styles.note}>
        Prices are set by the server ({quote.currency}). You are redirected to a
        secure checkout to pay; credit is added after payment confirms.
      </Text>
      <Pressable
        style={[styles.confirm, submitting && styles.disabled]}
        disabled={submitting}
        onPress={onConfirm}
        accessibilityRole="button"
        accessibilityLabel="Confirm and continue to checkout"
      >
        {submitting ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={styles.confirmText}>Continue to checkout</Text>
        )}
      </Pressable>
      <Pressable
        style={styles.dismiss}
        disabled={submitting}
        onPress={onDismiss}
        accessibilityRole="button"
      >
        <Text style={styles.dismissText}>Choose a different amount</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  sheet: {
    backgroundColor: colors.card,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 16,
    gap: 4,
  },
  title: {
    color: colors.textPrimary,
    fontSize: 16,
    fontWeight: "700",
    marginBottom: 8,
  },
  line: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingVertical: 6,
  },
  lineLabel: { color: colors.textSecondary, fontSize: 14 },
  lineValue: { color: colors.textPrimary, fontSize: 14 },
  strong: { color: colors.textPrimary, fontSize: 16, fontWeight: "700" },
  note: {
    color: colors.muted,
    fontSize: 12,
    lineHeight: 17,
    marginTop: 8,
    marginBottom: 12,
  },
  confirm: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 13,
    alignItems: "center",
  },
  disabled: { opacity: 0.6 },
  confirmText: { color: "#fff", fontSize: 15, fontWeight: "600" },
  dismiss: { paddingVertical: 12, alignItems: "center" },
  dismissText: { color: colors.textSecondary, fontSize: 13 },
});
