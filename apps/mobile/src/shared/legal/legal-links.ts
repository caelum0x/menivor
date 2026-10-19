/**
 * Terms of Service + Privacy Policy destinations.
 *
 * Apple Guideline 3.1.2 and account/onboarding review require FUNCTIONAL links
 * to a EULA/Terms page and a Privacy Policy at every point a subscription is
 * offered and at account creation. The full documents ship inside the app at
 * /legal/terms and /legal/privacy, so the links always work (offline, and
 * before any public web page exists). A build can point the links at hosted
 * pages instead by setting EXPO_PUBLIC_TERMS_URL / EXPO_PUBLIC_PRIVACY_URL to a
 * live https URL.
 */

/** In-app routes for the bundled documents. */
export const TERMS_ROUTE = "/legal/terms" as const;
export const PRIVACY_ROUTE = "/legal/privacy" as const;
/** In-app route for the bundled Creator Contract (always in-app, never hosted). */
export const CREATOR_CONTRACT_ROUTE = "/legal/creator-contract" as const;

function httpsUrl(value: string | undefined): string | null {
  const trimmed = value?.trim() ?? "";
  return /^https:\/\//i.test(trimmed) ? trimmed : null;
}

/** Hosted Terms URL when configured for this build, otherwise null. */
export function hostedTermsUrl(): string | null {
  return httpsUrl(process.env.EXPO_PUBLIC_TERMS_URL);
}

/** Hosted Privacy Policy URL when configured for this build, otherwise null. */
export function hostedPrivacyUrl(): string | null {
  return httpsUrl(process.env.EXPO_PUBLIC_PRIVACY_URL);
}

/** Where "Terms of Service" leads: the hosted page, or the in-app route. */
export function termsUrl(): string {
  return hostedTermsUrl() ?? TERMS_ROUTE;
}

/** Where "Privacy Policy" leads: the hosted page, or the in-app route. */
export function privacyUrl(): string {
  return hostedPrivacyUrl() ?? PRIVACY_ROUTE;
}
