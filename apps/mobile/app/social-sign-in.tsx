import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { Stack } from "expo-router";

import type { Session } from "@supabase/supabase-js";

import { colors } from "@/components/me/theme";
import {
  createDeviceSession,
  isAbortError,
  me,
  type DeviceSession,
} from "@/lib/api";
import type { Me } from "@/lib/types";
import {
  getOrCreateInstallId,
  isAppleSignInSupported,
  SocialSignInCancelled,
  useSession,
  useSupabaseAuth,
} from "@/src/shared/auth";

type Pending = "apple" | "google" | "sync" | null;

/** Ask before a link that could move this install off an account with data. */
function confirmLink(profile: Me): Promise<boolean> {
  return new Promise((resolve) => {
    Alert.alert(
      "Link this sign-in?",
      `This device account has ${profile.jobs_count} reel${profile.jobs_count === 1 ? "" : "s"} and ${profile.credits} credit${profile.credits === 1 ? "" : "s"}. ` +
        "If this Apple or Google account is new to Menivor, they move with you. " +
        "If it already has a Menivor account (from another phone or the web), this device switches to that account and this device account's reels and credits stay behind.",
      [
        { text: "Cancel", style: "cancel", onPress: () => resolve(false) },
        { text: "Link", onPress: () => resolve(true) },
      ],
      { cancelable: true, onDismiss: () => resolve(false) },
    );
  });
}

function describeOutcome(previous: Me | null, next: DeviceSession, email: string): string {
  if (previous && previous.user_id !== next.user_id) {
    return `Switched to the existing Menivor account for ${email} (${next.credits} credits). Your previous device account was left unchanged.`;
  }
  if (next.created) {
    return `Created a Menivor account for ${email}. You can sign in with it on any device.`;
  }
  return `Linked ${email} to this account. Your reels and ${next.credits} credits now sync across devices.`;
}

/**
 * Optional social account linking. Adds an Apple / Google identity (via Supabase)
 * on top of the existing device/API-key session so a user can sync their account
 * across installs. Reachable from the Me tab; not a hard gate on the app.
 *
 * The server decides the resulting account (device account adopted, or the
 * identity's existing account); this screen warns before a link that could
 * leave data behind and reports which account is active afterwards.
 */
export default function SocialSignInScreen() {
  const {
    configured,
    googleSupported,
    loading,
    session: identitySession,
    user,
    signInWithApple,
    signInWithGoogle,
    signOut,
  } = useSupabaseAuth();
  const { apiKey, signIn } = useSession();
  const [pending, setPending] = useState<Pending>(null);
  const [error, setError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<string | null>(null);
  const [profile, setProfile] = useState<Me | null>(null);

  useEffect(() => {
    if (!apiKey) {
      setProfile(null);
      return undefined;
    }
    const controller = new AbortController();
    me({ token: apiKey, signal: controller.signal })
      .then(setProfile)
      .catch((err: unknown) => {
        if (!isAbortError(err)) setProfile(null);
      });
    return () => controller.abort();
  }, [apiKey]);

  /** Exchange a verified identity token for this install's backend session. */
  const exchange = useCallback(
    async (accessToken: string, email: string) => {
      const installId = await getOrCreateInstallId();
      const platform = Platform.OS === "ios" ? "ios" : "android";
      const next = await createDeviceSession(installId, platform, accessToken);
      if (next.linked !== true) {
        throw new Error("The server did not confirm the link. Please try again.");
      }
      const previous = profile;
      await signIn(next.api_key);
      setOutcome(describeOutcome(previous, next, email));
      setProfile(null);
    },
    [profile, signIn],
  );

  /**
   * Link = establish the Apple/Google identity, then re-mint the backend session
   * with that identity's access token so the server attaches this identity to
   * the account (and returns the same account on any later install/device).
   */
  const run = async (which: "apple" | "google", op: () => Promise<Session>) => {
    setError(null);
    setOutcome(null);
    if (profile && (profile.jobs_count > 0 || profile.credits > 0)) {
      const ok = await confirmLink(profile);
      if (!ok) return;
    }
    setPending(which);
    let identityEstablished = false;
    try {
      const next = await op();
      identityEstablished = true;
      await exchange(next.access_token, next.user.email ?? "your account");
    } catch (err) {
      if (err instanceof SocialSignInCancelled) return;
      // Keep the screen honest: an identity the server never linked must not
      // show as "signed in", so roll the local Apple/Google session back.
      if (identityEstablished) await signOut().catch(() => undefined);
      setError(err instanceof Error ? err.message : "Sign-in could not be completed.");
    } finally {
      setPending(null);
    }
  };

  const resync = async () => {
    if (!identitySession) return;
    setError(null);
    setOutcome(null);
    setPending("sync");
    try {
      await exchange(identitySession.access_token, user?.email ?? "your account");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sync could not be completed.");
    } finally {
      setPending(null);
    }
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Stack.Screen options={{ title: "Sign in" }} />

      <Text style={styles.title}>Sync your account</Text>
      <Text style={styles.intro}>
        Link an Apple or Google identity to sync your Menivor account across
        devices. This is optional — you can keep using your device account.
      </Text>

      {!configured ? (
        <View style={styles.card}>
          <Text style={styles.body}>
            Apple and Google sign-in are not available in this version of the
            app. Your device account keeps working, and you can restore it on this
            install from Account Access.
          </Text>
        </View>
      ) : loading ? (
        <ActivityIndicator color={colors.accent} style={styles.loader} />
      ) : user ? (
        <View style={styles.card}>
          <Text style={styles.label}>Linked sign-in</Text>
          <Text selectable style={styles.email}>
            {user.email ?? user.id}
          </Text>
          <Text style={styles.body}>
            This install uses the Menivor account tied to this sign-in. Use the
            same Apple or Google account on another device to reach the same
            reels and credits.
          </Text>
          <Pressable
            style={[styles.secondary, pending !== null && styles.disabled]}
            disabled={pending !== null}
            onPress={() => void resync()}
            accessibilityRole="button"
          >
            {pending === "sync" ? (
              <ActivityIndicator color={colors.textPrimary} />
            ) : (
              <Text style={styles.secondaryText}>Sync this device again</Text>
            )}
          </Pressable>
          <Pressable
            style={styles.secondary}
            onPress={() => void signOut()}
            accessibilityRole="button"
          >
            <Text style={styles.secondaryText}>Disconnect sign-in on this device</Text>
          </Pressable>
        </View>
      ) : (
        <View style={styles.card}>
          {profile ? (
            <Text style={styles.body}>
              If this Apple or Google account already has a Menivor account, this
              device switches to it and this device account ({profile.jobs_count}{" "}
              reel{profile.jobs_count === 1 ? "" : "s"}, {profile.credits} credit
              {profile.credits === 1 ? "" : "s"}) stays behind. Otherwise your
              reels and credits move with you.
            </Text>
          ) : null}
          {isAppleSignInSupported() ? (
            <Pressable
              style={[styles.apple, pending !== null && styles.disabled]}
              disabled={pending !== null}
              onPress={() => void run("apple", signInWithApple)}
              accessibilityRole="button"
              accessibilityLabel="Continue with Apple"
            >
              {pending === "apple" ? (
                <ActivityIndicator color="#ffffff" />
              ) : (
                <Text style={styles.appleText}>Continue with Apple</Text>
              )}
            </Pressable>
          ) : null}

          {googleSupported ? (
            <Pressable
              style={[styles.google, pending !== null && styles.disabled]}
              disabled={pending !== null}
              onPress={() => void run("google", signInWithGoogle)}
              accessibilityRole="button"
              accessibilityLabel="Continue with Google"
            >
              {pending === "google" ? (
                <ActivityIndicator color="#1f1f1f" />
              ) : (
                <Text style={styles.googleText}>Continue with Google</Text>
              )}
            </Pressable>
          ) : (
            <Text style={styles.note}>
              Google sign-in is not available in this build yet. Use Apple above,
              or keep using your device account.
            </Text>
          )}
        </View>
      )}

      {outcome ? <Text style={styles.success}>{outcome}</Text> : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20, paddingTop: 24, gap: 16 },
  title: { color: colors.textPrimary, fontSize: 26, fontWeight: "800" },
  intro: { color: colors.textSecondary, fontSize: 14, lineHeight: 21 },
  loader: { marginTop: 24 },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 18,
    gap: 14,
  },
  label: { color: colors.muted, fontSize: 12, fontWeight: "700" },
  email: { color: colors.textPrimary, fontSize: 15, fontWeight: "600" },
  body: { color: colors.textSecondary, fontSize: 13, lineHeight: 19 },
  apple: {
    minHeight: 50,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 12,
    backgroundColor: "#000000",
    borderColor: "#ffffff",
    borderWidth: 1,
  },
  appleText: { color: "#ffffff", fontSize: 15, fontWeight: "700" },
  google: {
    minHeight: 50,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 12,
    backgroundColor: "#ffffff",
  },
  googleText: { color: "#1f1f1f", fontSize: 15, fontWeight: "700" },
  note: { color: colors.textSecondary, fontSize: 13, lineHeight: 19 },
  secondary: {
    minHeight: 46,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 12,
    borderColor: colors.border,
    borderWidth: 1,
  },
  secondaryText: { color: colors.textSecondary, fontSize: 14, fontWeight: "600" },
  disabled: { opacity: 0.5 },
  error: { color: colors.error, fontSize: 13, lineHeight: 19 },
  success: { color: colors.success, fontSize: 13, lineHeight: 19 },
});
