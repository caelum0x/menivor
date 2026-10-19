/**
 * Terms of Service + Privacy Policy (+ Creator Contract) links. Opens the hosted page in the in-app
 * browser when configured, otherwise the bundled in-app document. Rendered at
 * sign-in (account creation) and on every paywall surface so the subscription offer meets Apple Guideline 3.1.2.
 *
 * `tint` lets a caller match the surrounding surface (e.g. the light paywall
 * card vs. the dark gradient sign-in screen). No secrets or user data here.
 */

import { StyleSheet, Text, View } from "react-native";

import * as Linking from "expo-linking";
import { useRouter } from "expo-router";
import * as WebBrowser from "expo-web-browser";

import {
  CREATOR_CONTRACT_ROUTE,
  hostedPrivacyUrl,
  hostedTermsUrl,
  PRIVACY_ROUTE,
  TERMS_ROUTE,
} from "./legal-links";

async function openUrl(url: string): Promise<void> {
  try {
    await WebBrowser.openBrowserAsync(url);
    return;
  } catch {
    // Fall through to the system browser.
  }
  const canOpen = await Linking.canOpenURL(url).catch(() => false);
  if (canOpen) await Linking.openURL(url);
}

export interface LegalLinksProps {
  /** Text color for the two links. Defaults to the app accent. */
  tint?: string;
  /** Optional separator/label color. Defaults to a muted grey. */
  mutedTint?: string;
  /**
   * Also link the Creator Contract (credits never expire, failed renders
   * refunded, no training on your content). On by default so every paywall
   * and the sign-in screen carry it.
   */
  showContract?: boolean;
}

export function LegalLinks({
  tint = "#E6C76A",
  mutedTint = "#9b978d",
  showContract = true,
}: Readonly<LegalLinksProps>) {
  const router = useRouter();
  // Hosted page when the build configures one; otherwise the bundled in-app
  // document, which is always reachable (no network, no session needed).
  const open = (
    hosted: string | null,
    route: typeof TERMS_ROUTE | typeof PRIVACY_ROUTE,
  ) => {
    if (hosted) {
      void openUrl(hosted);
      return;
    }
    router.push(route);
  };
  return (
    <View style={styles.row}>
      <Text
        style={[styles.link, { color: tint }]}
        accessibilityRole="link"
        accessibilityLabel="Open Terms of Service"
        onPress={() => open(hostedTermsUrl(), TERMS_ROUTE)}
      >
        Terms of Service
      </Text>
      <Text style={[styles.separator, { color: mutedTint }]}>·</Text>
      <Text
        style={[styles.link, { color: tint }]}
        accessibilityRole="link"
        accessibilityLabel="Open Privacy Policy"
        onPress={() => open(hostedPrivacyUrl(), PRIVACY_ROUTE)}
      >
        Privacy Policy
      </Text>
      {showContract ? (
        <>
          <Text style={[styles.separator, { color: mutedTint }]}>·</Text>
          <Text
            style={[styles.link, { color: tint }]}
            accessibilityRole="link"
            accessibilityLabel="Open the Creator Contract"
            onPress={() => router.push(CREATOR_CONTRACT_ROUTE)}
          >
            Creator Contract
          </Text>
        </>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    flexWrap: "wrap",
    gap: 8,
  },
  link: {
    fontSize: 13,
    fontWeight: "700",
    textDecorationLine: "underline",
  },
  separator: { fontSize: 13, fontWeight: "700" },
});
