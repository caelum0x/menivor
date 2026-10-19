/**
 * Opens a hosted-checkout URL from the billing surfaces, preferring the in-app
 * browser (expo-web-browser) and falling back to the system browser
 * (expo-linking). Shared by the team-credits purchase panel and the ENTERPRISE
 * Plan & Usage upgrade CTA so both open checkout identically.
 *
 * MONEY-CORRECTNESS: this only *navigates* the buyer to the provider's page.
 * No credits or entitlements are granted client-side — the backend fulfils the
 * purchase idempotently on the provider webhook. No secrets are handled here.
 */

import { Platform } from "react-native";

import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";

/**
 * STORE POLICY: App Store Guideline 3.1.1 and Google Play's payments policy
 * require digital goods (generation credits, plan upgrades) bought inside a
 * store-distributed app to use the store's in-app purchase system. The mobile
 * app therefore sells only Menivor Pro (RevenueCat / store IAP) and never opens
 * a hosted web checkout on iOS or Android. Web builds, and internal/enterprise
 * builds that set EXPO_PUBLIC_EXTERNAL_CHECKOUT=1, keep the hosted checkout.
 */
export function externalCheckoutAvailable(): boolean {
  if (Platform.OS === "web") return true;
  return process.env.EXPO_PUBLIC_EXTERNAL_CHECKOUT?.trim() === "1";
}

/**
 * Open `url` in the in-app browser, falling back to the system browser. Throws
 * with a user-facing message when neither can open it (e.g. a malformed URL).
 */
export async function openCheckoutUrl(url: string): Promise<void> {
  if (!externalCheckoutAvailable()) {
    throw new Error("Purchases in this app are made through Menivor Pro.");
  }
  try {
    await WebBrowser.openBrowserAsync(url);
    return;
  } catch {
    // Fall through to the system browser.
  }
  const canOpen = await Linking.canOpenURL(url).catch(() => false);
  if (!canOpen) {
    throw new Error("Couldn't open the checkout page on this device.");
  }
  await Linking.openURL(url);
}
