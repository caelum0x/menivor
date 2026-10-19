/**
 * Renders a generation/export error. Payment-required failures (402) get a
 * plain-language explanation and a way forward instead of the raw backend
 * string: "out of credits" links to the wallet top-up (store credit packs on
 * store builds), "Pro required" opens the Menivor Pro paywall. Any other error
 * is shown as text with the request-id prefix stripped.
 */

import { useState } from "react";
import {
  Pressable,
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type TextStyle,
} from "react-native";

import { useRouter } from "expo-router";

import { Icon } from "@/components/ui/Icon";
import { useRevenueCat } from "@/src/shared/billing";
import { colors, radius, spacing, typeScale } from "@/src/shared/theme";

export type PaymentRequiredKind = "credits" | "pro";

const CREDIT_PATTERNS: readonly RegExp[] = [
  /insufficient credits/i,
  /not enough credits/i,
  /credit allocation is exhausted/i,
  /above the internal-pilot per-request cap/i,
  /empty pool/i,
];
const PRO_PATTERNS: readonly RegExp[] = [/active Pro entitlement is required/i];

/** Classify an API error message as a payment-required failure, if it is one. */
export function paymentRequiredKind(message: string | null | undefined): PaymentRequiredKind | null {
  if (!message) return null;
  if (PRO_PATTERNS.some((pattern) => pattern.test(message))) return "pro";
  if (CREDIT_PATTERNS.some((pattern) => pattern.test(message))) return "credits";
  return null;
}

/** Drop the leading "<request_id>: " the API prefixes onto error messages. */
export function stripRequestId(message: string): string {
  return message.replace(/^[A-Za-z0-9_-]{8,}:\s+/, "").trim();
}

export interface GenerationErrorNoticeProps {
  readonly message: string | null | undefined;
  /** Text style used for ordinary (non-payment) errors. */
  readonly style?: StyleProp<TextStyle>;
}

export function GenerationErrorNotice({ message, style }: GenerationErrorNoticeProps) {
  const router = useRouter();
  const { presentPaywall } = useRevenueCat();
  const [paywallError, setPaywallError] = useState<string | null>(null);

  if (!message) return null;
  const kind = paymentRequiredKind(message);
  if (!kind) {
    return <Text style={style ?? styles.plainError}>{stripRequestId(message)}</Text>;
  }

  const onPress = async () => {
    setPaywallError(null);
    if (kind === "credits") {
      router.push("/wallet/top-up");
      return;
    }
    const next = await presentPaywall();
    if (next.status !== "active" && next.status !== "inactive" && next.message) {
      setPaywallError(next.message);
    }
  };

  return (
    <View style={styles.card} accessibilityRole="alert">
      <View style={styles.header}>
        <Icon
          name={kind === "credits" ? "wallet-outline" : "lock-closed-outline"}
          size={18}
          color={colors.accent}
        />
        <Text style={styles.title}>
          {kind === "credits" ? "You're out of credits" : "Menivor Pro required"}
        </Text>
      </View>
      <Text style={styles.body}>
        {kind === "credits"
          ? "This generation costs more credits than your wallet has. Add credits and run it again; nothing was charged for this attempt."
          : "Export, the clean MP4, share links and publishing are part of Menivor Pro."}
      </Text>
      <Pressable
        style={styles.button}
        onPress={() => void onPress()}
        accessibilityRole="button"
      >
        <Text style={styles.buttonText}>
          {kind === "credits" ? "Add credits" : "See Menivor Pro"}
        </Text>
      </Pressable>
      {paywallError ? <Text style={styles.plainError}>{paywallError}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderColor: colors.accent,
    borderWidth: 1,
    borderRadius: radius.lg,
    padding: spacing.lg,
    gap: spacing.sm,
    marginVertical: spacing.sm,
  },
  header: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  title: { color: colors.textPrimary, fontSize: typeScale.subheading, fontWeight: "700" },
  body: { color: colors.textSecondary, fontSize: typeScale.caption, lineHeight: 19 },
  button: {
    backgroundColor: colors.accent,
    borderRadius: radius.md,
    paddingVertical: 11,
    alignItems: "center",
    marginTop: spacing.xs,
  },
  buttonText: { color: colors.onAccent, fontSize: typeScale.body, fontWeight: "700" },
  plainError: { color: colors.danger, fontSize: typeScale.caption },
});
