/**
 * Auto-renewing subscription disclosure for Menivor Pro.
 *
 * Apple Guideline 3.1.2 requires that wherever an auto-renewing subscription is
 * offered the app states, in plain language: the subscription renews
 * automatically, how it is billed, and how to cancel — alongside functional
 * Terms (EULA) and Privacy Policy links. This block is rendered on the paywall
 * surfaces (membership + export/publishing access cards) when Pro is not yet
 * active, i.e. wherever the "Upgrade / Unlock" action lives.
 */

import { StyleSheet, Text, View } from "react-native";

import { LegalLinks } from "./LegalLinks";

export interface SubscriptionDisclosureProps {
  /** Text color for the disclosure copy. */
  textColor?: string;
  /** Text color for the Terms / Privacy links. */
  linkTint?: string;
}

export function SubscriptionDisclosure({
  textColor = "#9b978d",
  linkTint = "#E6C76A",
}: Readonly<SubscriptionDisclosureProps>) {
  return (
    <View style={styles.container}>
      <Text style={[styles.copy, { color: textColor }]}>
        Menivor Pro is an auto-renewing subscription. Payment is charged to your
        App Store or Google Play account at confirmation of purchase. It renews
        automatically for the same price and period unless you cancel at least 24
        hours before the current period ends. Manage or cancel anytime in your
        store account settings.
      </Text>
      <LegalLinks tint={linkTint} mutedTint={textColor} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { gap: 10, marginTop: 12 },
  copy: { fontSize: 12, lineHeight: 17 },
});
