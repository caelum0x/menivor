/**
 * Native token acquisition for social sign-in, exchanged for a Supabase session
 * via `supabase.auth.signInWithIdToken({ provider, token })`.
 *
 * Apple -> expo-apple-authentication; Google -> @react-native-google-signin.
 * Both yield an RS256 identity token that Supabase verifies server-side. Requires
 * a dev/production build (NOT Expo Go) with these native modules, the app.json
 * plugins, and a Google web client id in EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID.
 */

import { Platform } from "react-native";

import * as AppleAuthentication from "expo-apple-authentication";
import type { Session, SupabaseClient } from "@supabase/supabase-js";

type GoogleSigninModule = typeof import("@react-native-google-signin/google-signin");

let googleModule: GoogleSigninModule | null = null;

/**
 * Load the Google native module on first use only, so builds (and Expo Go)
 * without it never touch the native binding at startup.
 */
function loadGoogle(): GoogleSigninModule {
  if (!googleModule) {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    googleModule = require("@react-native-google-signin/google-signin") as GoogleSigninModule;
  }
  return googleModule;
}

/** Apple sign-in is iOS-only. Hide the button elsewhere. */
export const isAppleSignInSupported = (): boolean => Platform.OS === "ios";

/**
 * Native Google sign-in requires two build-time ingredients:
 *   1. A Google iOS OAuth client whose reverse-client URL scheme is registered
 *      in the native app via the `@react-native-google-signin/google-signin`
 *      config plugin in app.json (`iosUrlScheme`).
 *   2. A web client id in EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID (what Supabase's
 *      signInWithIdToken verifies against).
 *
 * The reverse-client scheme is tied to a specific bundle id. When the app ships
 * under a bundle id that has no matching Google iOS OAuth client (e.g. after the
 * com.menivor.app -> com.arhansuba.menivor move), there is no valid scheme to
 * register, so we deliberately DO NOT ship the plugin or a broken scheme — we
 * surface Google as unavailable instead of shipping a dead redirect.
 *
 * The presence of a web client id in the environment is the build-time signal
 * that the owner has wired a Google iOS OAuth client for THIS bundle. To
 * re-enable Google later: create a Google iOS OAuth client for the new bundle
 * id, add the google-signin plugin + its iosUrlScheme back to app.json, restore
 * EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID / EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID in
 * eas.json, and rebuild. See app.json and eas.json for the exact spots.
 */
export const isGoogleSignInSupported = (): boolean =>
  Boolean(process.env.EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID?.trim());

/** The user backed out of the native sheet — treat as a no-op, not an error. */
export class SocialSignInCancelled extends Error {
  constructor() {
    super("cancelled");
    this.name = "SocialSignInCancelled";
  }
}

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null;

/** Apple/Google both surface user-cancel via a small set of error codes. */
const isCancellation = (err: unknown): boolean => {
  if (!isRecord(err)) return false;
  const code = typeof err.code === "string" ? err.code : "";
  return (
    code === "ERR_REQUEST_CANCELED" || // Apple
    code === "ERR_CANCELED" ||
    code === "SIGN_IN_CANCELLED" || // Google
    code === "-5"
  );
};

let googleConfigured = false;
/** Configure Google sign-in once (idempotent). Call before {@link signInWithGoogle}. */
export const configureGoogleSignIn = (
  webClientId: string,
  iosClientId?: string,
): void => {
  if (googleConfigured || !webClientId) return;
  loadGoogle().GoogleSignin.configure(
    iosClientId ? { webClientId, iosClientId } : { webClientId },
  );
  googleConfigured = true;
};

/** Hand a verified native identity token to Supabase and return the session. */
async function establishSession(
  client: SupabaseClient,
  provider: "apple" | "google",
  token: string,
): Promise<Session> {
  const { data, error } = await client.auth.signInWithIdToken({
    provider,
    token,
  });
  if (error) throw error;
  if (!data.session) {
    throw new Error("Supabase did not return a session for this sign-in.");
  }
  return data.session;
}

/**
 * Run the native Apple flow and establish a Supabase session. `fullName` is only
 * present on the first authorization; Supabase keeps the derived profile row.
 */
export const signInWithApple = async (
  client: SupabaseClient,
): Promise<Session> => {
  try {
    const credential = await AppleAuthentication.signInAsync({
      requestedScopes: [
        AppleAuthentication.AppleAuthenticationScope.FULL_NAME,
        AppleAuthentication.AppleAuthenticationScope.EMAIL,
      ],
    });
    if (!credential.identityToken) {
      throw new Error("Apple sign-in returned no identity token.");
    }
    return await establishSession(client, "apple", credential.identityToken);
  } catch (err: unknown) {
    if (isCancellation(err)) throw new SocialSignInCancelled();
    throw err;
  }
};

/** Run the native Google flow and establish a Supabase session. */
export const signInWithGoogle = async (
  client: SupabaseClient,
): Promise<Session> => {
  if (!isGoogleSignInSupported()) {
    throw new Error(
      "Google sign-in is not available in this build. Use Sign in with Apple.",
    );
  }
  try {
    const { GoogleSignin } = loadGoogle();
    await GoogleSignin.hasPlayServices({ showPlayServicesUpdateDialog: true });
    const result: unknown = await GoogleSignin.signIn();
    // @react-native-google-signin surfaces the token at result.data.idToken on
    // the modern response shape; narrow defensively so this stays version-stable.
    const data = isRecord(result) && isRecord(result.data) ? result.data : null;
    const idToken =
      data && typeof data.idToken === "string" ? data.idToken : null;
    if (!idToken) throw new SocialSignInCancelled(); // cancelled result has no token
    return await establishSession(client, "google", idToken);
  } catch (err: unknown) {
    if (err instanceof SocialSignInCancelled) throw err;
    if (isCancellation(err)) throw new SocialSignInCancelled();
    throw err;
  }
};
