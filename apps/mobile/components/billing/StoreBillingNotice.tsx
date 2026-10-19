/**
 * Shown in place of a hosted-checkout purchase flow (credit top-ups, plan
 * upgrades) on store builds, where digital goods must go through in-app
 * purchase (see externalCheckoutAvailable). Points the creator at the one
 * thing the app does sell in-app: Menivor Pro, via the RevenueCat paywall.
 */

import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { Icon } from "@/components/ui/Icon";
import { useRevenueCat } from "@/src/shared/billing";
import { colors, radius, spacing, typeScale } from "@/src/shared/theme";

export interface StoreBillingNoticeProps {
  /** What the hidden flow was for, e.g. "Credit top-ups". */
  readonly subject: string;
  /** Overrides the default "<subject> are not sold in the mobile app" title. */
  readonly title?: string;
  /** Overrides the default explanation paragraph. */
  readonly body?: string;
}

export function StoreBillingNotice({ subject, title, body }: StoreBillingNoticeProps) {
  const { presentPaywall, snapshot } = useRevenueCat();
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const active = snapshot.status === "active";

  const onOpen = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const next = await presentPaywall();
      if (next.status !== "active" && next.message) setMessage(next.message);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Could not open Menivor Pro.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.card}>
      <Icon name="lock-closed-outline" size={22} color={colors.textSecondary} />
      <Text style={styles.title}>{title ?? `${subject} are not sold in the mobile app`}</Text>
      <Text style={styles.body}>
        {body ??
          "Your wallet balance and history stay available in Wallet. In the app, Menivor Pro is the in-app subscription: it unlocks export, public share links and scheduled publishing."}
      </Text>
      {active ? (
        <Text style={styles.body}>Menivor Pro is active on this account.</Text>
      ) : (
        <Pressable
          style={[styles.button, busy && styles.disabled]}
          onPress={() => void onOpen()}
          disabled={busy}
          accessibilityRole="button"
        >
          <Text style={styles.buttonText}>See Menivor Pro</Text>
        </Pressable>
      )}
      {message ? <Text style={styles.error}>{message}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.lg,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  title: {
    color: colors.textPrimary,
    fontSize: typeScale.subheading,
    fontWeight: "700",
  },
  body: { color: colors.textSecondary, fontSize: typeScale.caption, lineHeight: 19 },
  button: {
    backgroundColor: colors.accent,
    borderRadius: radius.md,
    paddingVertical: 12,
    alignItems: "center",
    marginTop: spacing.xs,
  },
  buttonText: { color: colors.onAccent, fontSize: typeScale.body, fontWeight: "700" },
  disabled: { opacity: 0.5 },
  error: { color: colors.danger, fontSize: typeScale.caption },
});
