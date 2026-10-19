/**
 * Open the Terms of Service, Privacy Policy or Creator Contract from any screen: the hosted page
 * in the in-app browser when the build configures one, otherwise the bundled
 * in-app document (always reachable, offline and signed in or out).
 */

import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";

import {
  CREATOR_CONTRACT_ROUTE,
  hostedPrivacyUrl,
  hostedTermsUrl,
  PRIVACY_ROUTE,
  TERMS_ROUTE,
} from "./legal-links";

export type LegalDocumentKind = "terms" | "privacy" | "contract";

interface LegalRouter {
  push: (
    href: typeof TERMS_ROUTE | typeof PRIVACY_ROUTE | typeof CREATOR_CONTRACT_ROUTE,
  ) => void;
}

async function openHosted(url: string): Promise<boolean> {
  try {
    await WebBrowser.openBrowserAsync(url);
    return true;
  } catch {
    // Fall through to the system browser.
  }
  const canOpen = await Linking.canOpenURL(url).catch(() => false);
  if (!canOpen) return false;
  await Linking.openURL(url);
  return true;
}

export function openLegalDocument(kind: LegalDocumentKind, router: LegalRouter): void {
  // The Creator Contract always opens the bundled in-app copy.
  if (kind === "contract") {
    router.push(CREATOR_CONTRACT_ROUTE);
    return;
  }
  const hosted = kind === "terms" ? hostedTermsUrl() : hostedPrivacyUrl();
  const route = kind === "terms" ? TERMS_ROUTE : PRIVACY_ROUTE;
  if (!hosted) {
    router.push(route);
    return;
  }
  void openHosted(hosted).then((opened) => {
    if (!opened) router.push(route);
  });
}
