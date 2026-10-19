/**
 * A horizontal, single-select row of payment-provider chips. The offered
 * providers are the ENABLED ones from GET /billing/providers (Stripe / iyzico /
 * Creem / Polar) — this component is purely presentational: selection state is
 * owned by the parent, which passes the chosen provider on to createCheckout.
 * No network and no secrets here.
 */

import { Pressable, StyleSheet, Text, View } from "react-native";

import type { PaymentProvider } from "@/lib/types";

import { colors } from "@/components/me/theme";
import { orderProviders, providerLabel } from "./providers";

export interface ProviderChipsProps {
  /** Enabled providers to offer (from getProviders); rendered in canonical order. */
  providers: readonly (PaymentProvider | string)[];
  /** Currently selected provider, or null when none is chosen/available. */
  selected: PaymentProvider | string | null;
  onSelect: (provider: PaymentProvider | string) => void;
  disabled?: boolean;
}

export function ProviderChips({
  providers,
  selected,
  onSelect,
  disabled = false,
}: Readonly<ProviderChipsProps>) {
  const ordered = orderProviders(providers);
  if (ordered.length === 0) return null;

  return (
    <View style={styles.wrap}>
      {ordered.map((provider) => {
        const active = provider === selected;
        return (
          <Pressable
            key={provider}
            style={[
              styles.chip,
              active && styles.chipActive,
              disabled && styles.chipDisabled,
            ]}
            onPress={() => onSelect(provider)}
            disabled={disabled}
            accessibilityRole="radio"
            accessibilityState={{ selected: active, disabled }}
            accessibilityLabel={`Pay with ${providerLabel(provider)}`}
          >
            <Text style={[styles.chipText, active && styles.chipTextActive]}>
              {providerLabel(provider)}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipDisabled: { opacity: 0.5 },
  chipText: { color: colors.textSecondary, fontSize: 13 },
  chipTextActive: { color: colors.textPrimary, fontWeight: "700" },
});
