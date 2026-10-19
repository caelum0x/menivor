/**
 * Optional Supabase social-auth layer, provided alongside the existing API-key
 * session (see ./session). It tracks the Supabase session + user and exposes
 * Apple/Google sign-in. It is purely additive: when Supabase is not configured
 * the provider is inert and `configured` is false, so the app behaves exactly as
 * it did before.
 *
 * RevenueCat identity is deliberately NOT touched here. The backend's Pro check
 * (require_pro_action) verifies the entitlement against the backend user id, so
 * RevenueCatProvider owns the RC app-user id and always logs in as that id.
 * Re-identifying RC as the Supabase uid would hide purchases from the server.
 * Sign-in resolves with the Supabase session so callers can forward the access
 * token to POST /auth/device when minting the backend session.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type PropsWithChildren,
} from "react";

import type { Session, User } from "@supabase/supabase-js";
import Constants from "expo-constants";

import {
  isEmailSignInEnabled,
  requestEmailCode as sendEmailCode,
  verifyEmailCode as checkEmailCode,
} from "./email-otp";
import { getSupabaseClient, isSupabaseConfigured } from "./supabase";
import {
  configureGoogleSignIn,
  isGoogleSignInSupported,
  signInWithApple as runAppleSignIn,
  signInWithGoogle as runGoogleSignIn,
} from "./social-signin";

export interface SupabaseAuthValue {
  /** True when the Supabase env vars are present for this build. */
  configured: boolean;
  /**
   * True only when native Google sign-in is wired for this build's bundle id
   * (a Google iOS OAuth client + web client id). False when the app ships under
   * a bundle id with no matching Google client — the UI hides Google then and
   * offers Apple / no-account instead. See social-signin.isGoogleSignInSupported.
   */
  googleSupported: boolean;
  /** True when this build offers email one-time-code sign-in (see ./email-otp). */
  emailEnabled: boolean;
  /** True until the persisted Supabase session has loaded on startup. */
  loading: boolean;
  session: Session | null;
  user: User | null;
  signInWithApple: () => Promise<Session>;
  signInWithGoogle: () => Promise<Session>;
  /** Email a one-time sign-in code (creates the account on first use). */
  requestEmailCode: (email: string) => Promise<void>;
  /** Verify the emailed code and resolve with the Scribase session. */
  verifyEmailCode: (email: string, code: string) => Promise<Session>;
  signOut: () => Promise<void>;
}

const EMAIL_SIGN_IN = isEmailSignInEnabled(Constants.expoConfig?.extra, {
  EXPO_PUBLIC_EMAIL_SIGNIN: process.env.EXPO_PUBLIC_EMAIL_SIGNIN,
});

const SupabaseAuthContext = createContext<SupabaseAuthValue | null>(null);

function clean(value: string | undefined): string {
  return value?.trim() ?? "";
}

export function SupabaseAuthProvider({ children }: PropsWithChildren) {
  const configured = isSupabaseConfigured();
  const googleSupported = isGoogleSignInSupported();
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(configured);

  useEffect(() => {
    const client = getSupabaseClient();
    if (!client) {
      setLoading(false);
      return undefined;
    }

    // Only touch the native Google module when a Google client is actually
    // wired for this bundle id; otherwise leave it inert (see googleSupported).
    if (googleSupported) {
      configureGoogleSignIn(
        clean(process.env.EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID),
        clean(process.env.EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID) || undefined,
      );
    }

    let active = true;
    client.auth
      .getSession()
      .then(({ data }) => {
        if (active) setSession(data.session);
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    const { data: subscription } = client.auth.onAuthStateChange(
      (_event, nextSession) => {
        if (active) setSession(nextSession);
      },
    );

    return () => {
      active = false;
      subscription.subscription.unsubscribe();
    };
  }, []);

  const signInWithApple = useCallback(async () => {
    const client = getSupabaseClient();
    if (!client) throw new Error("Supabase is not configured for this build.");
    const next = await runAppleSignIn(client);
    setSession(next);
    return next;
  }, []);

  const signInWithGoogle = useCallback(async () => {
    const client = getSupabaseClient();
    if (!client) throw new Error("Supabase is not configured for this build.");
    const next = await runGoogleSignIn(client);
    setSession(next);
    return next;
  }, []);

  const requestEmailCode = useCallback(async (email: string) => {
    await sendEmailCode(getSupabaseClient(), email);
  }, []);

  const verifyEmailCode = useCallback(async (email: string, code: string) => {
    const next = await checkEmailCode(getSupabaseClient(), email, code);
    setSession(next);
    return next;
  }, []);

  const signOut = useCallback(async () => {
    const client = getSupabaseClient();
    if (!client) return;
    await client.auth.signOut();
    setSession(null);
  }, []);

  const value = useMemo<SupabaseAuthValue>(
    () => ({
      configured,
      googleSupported,
      emailEnabled: EMAIL_SIGN_IN,
      loading,
      session,
      user: session?.user ?? null,
      signInWithApple,
      signInWithGoogle,
      requestEmailCode,
      verifyEmailCode,
      signOut,
    }),
    [
      configured,
      googleSupported,
      loading,
      session,
      signInWithApple,
      signInWithGoogle,
      requestEmailCode,
      verifyEmailCode,
      signOut,
    ],
  );

  return (
    <SupabaseAuthContext.Provider value={value}>
      {children}
    </SupabaseAuthContext.Provider>
  );
}

/** Access the Supabase auth state. Must be used under <SupabaseAuthProvider>. */
export function useSupabaseAuth(): SupabaseAuthValue {
  const ctx = useContext(SupabaseAuthContext);
  if (!ctx) {
    throw new Error(
      "useSupabaseAuth must be used within a SupabaseAuthProvider",
    );
  }
  return ctx;
}
