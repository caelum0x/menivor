import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import * as AppleAuthentication from "expo-apple-authentication";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import type { Session } from "@supabase/supabase-js";

import { ApiError, createDeviceSession } from "@/lib/api";
import { getBetaLaunchStatus, type LaunchPhase } from "@/lib/beta";
import { Icon } from "@/components/ui/Icon";
import {
  getOrCreateInstallId,
  isAppleSignInSupported,
  SocialSignInCancelled,
  useSession,
  useSupabaseAuth,
} from "@/src/shared/auth";
import { EmailCodeSignIn } from "@/src/shared/auth/EmailCodeSignIn";
import { LegalLinks } from "@/src/shared/legal";
import { isDemoMode, isDevBuild } from "@/src/shared/release/build-flags";
import { DEMO_API_KEY } from "@/src/shared/release/demo-data";
import { colors, kicker } from "@/src/shared/theme";
import { ReelWall, goldPressDepth } from "@/src/ui/menivor";

/**
 * Menivor sign-in. A wall of moving niche reels behind one calm panel. An
 * account is required before anything is made: Sign in with Apple (native
 * button), email with a one-time code (when the build enables it) or Google.
 * There is no guest mode; the access-key path is a dev-session tool only.
 *
 * After the Apple/Google identity is established, the backend mints the
 * Menivor session for that named account (same account on reinstall or a new
 * device). 403 means public signup is closed for this launch phase, which
 * routes to early access / the waitlist; anything else stays here, retryable.
 */
type SocialProvider = "apple" | "google" | "email";

function isSignupClosed(err: unknown): boolean {
  return err instanceof ApiError && err.status === 403;
}

function sessionErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status >= 500) {
      return "Menivor is briefly unavailable. Try again in a moment.";
    }
    return err.message || "Sign-in could not be completed. Try again.";
  }
  return "Could not reach Menivor. Check your connection and try again.";
}

export default function SignInScreen() {
  const { apiKey, loading, signIn } = useSession();
  const insets = useSafeAreaInsets();
  const { next } = useLocalSearchParams<{ next?: string }>();
  const nextPath =
    typeof next === "string" && /^\/invite\/[A-Za-z0-9._~-]+$/.test(next) ? next : null;
  const {
    configured: socialConfigured,
    googleSupported,
    emailEnabled,
    signInWithApple,
    signInWithGoogle,
    requestEmailCode,
    verifyEmailCode,
  } = useSupabaseAuth();
  const router = useRouter();
  const demo = isDemoMode();
  const [pending, setPending] = useState<SocialProvider | "key" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [phase, setPhase] = useState<LaunchPhase | null>(null);
  const [showKey, setShowKey] = useState(false);
  const [keyValue, setKeyValue] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    getBetaLaunchStatus({ signal: controller.signal })
      .then((status) => setPhase(status.phase))
      .catch(() => undefined);
    return () => controller.abort();
  }, []);
  const privateBeta = phase === "private_beta";
  const busy = pending !== null;

  if (loading) {
    return (
      <View style={[styles.container, styles.center]}>
        <ActivityIndicator color={colors.accent} size="large" />
      </View>
    );
  }

  if (apiKey) return <Redirect href={nextPath ?? "/(tabs)/create"} />;

  const continueWith = async (provider: SocialProvider, op: () => Promise<Session>) => {
    setPending(provider);
    setError(null);
    if (demo) {
      // Dev-only seeded workspace for screenshots; never reachable in a store build.
      await signIn(DEMO_API_KEY);
      return;
    }
    let identityToken: string;
    try {
      identityToken = (await op()).access_token;
    } catch (err) {
      setPending(null);
      if (err instanceof SocialSignInCancelled) return;
      setError(err instanceof Error ? err.message : "Sign-in could not be completed.");
      return;
    }
    try {
      const installId = await getOrCreateInstallId();
      const platform = Platform.OS === "ios" ? "ios" : "android";
      const session = await createDeviceSession(installId, platform, identityToken);
      await signIn(session.api_key);
    } catch (err) {
      setPending(null);
      if (isSignupClosed(err)) {
        router.push(privateBeta ? "/beta-request" : "/waitlist");
        return;
      }
      setError(sessionErrorMessage(err));
    }
  };

  const signInWithKey = async () => {
    const trimmed = keyValue.trim();
    if (!trimmed) {
      setError("Enter an access key.");
      return;
    }
    setPending("key");
    try {
      await signIn(trimmed);
    } catch (err) {
      setPending(null);
      setError(err instanceof Error ? err.message : "Could not save that key.");
    }
  };

  const appleAvailable = isAppleSignInSupported() && (socialConfigured || demo);
  const googleAvailable = googleSupported && (socialConfigured || demo);
  const emailAvailable = emailEnabled && (socialConfigured || demo);
  const anyProvider = appleAvailable || googleAvailable || emailAvailable;

  return (
    <View style={styles.container}>
      <ReelWall />

      <View style={[styles.content, { paddingTop: insets.top + 28, paddingBottom: insets.bottom + 20 }]}>
        <View style={styles.brandRow}>
          <View style={styles.brandMark}>
            <Icon name="play" size={14} color={colors.onAccent} />
          </View>
          <Text style={styles.brand}>Menivor</Text>
        </View>

        <View style={styles.panel}>
          <Text style={styles.kicker}>PROMPT / LINK / FOOTAGE</Text>
          <Text style={styles.title} accessibilityRole="header">
            Type an idea.{"\n"}Get a reel.
          </Text>
          <Text style={styles.subtitle}>
            Menivor writes the hook, voices it, cuts the b-roll and burns in word-by-word
            captions. You edit, then export.
          </Text>

          {privateBeta ? (
            <Pressable
              style={({ pressed }) => [styles.primary, { boxShadow: goldPressDepth(pressed) }]}
              onPress={() => router.push("/beta-request")}
              disabled={busy}
              accessibilityRole="button"
            >
              <Text style={styles.primaryText}>Request early access</Text>
            </Pressable>
          ) : null}

          {appleAvailable ? (
            pending === "apple" ? (
              <View style={[styles.providerBusy]}>
                <ActivityIndicator color={colors.textPrimary} />
              </View>
            ) : (
              <AppleAuthentication.AppleAuthenticationButton
                buttonType={AppleAuthentication.AppleAuthenticationButtonType.CONTINUE}
                buttonStyle={AppleAuthentication.AppleAuthenticationButtonStyle.WHITE}
                cornerRadius={14}
                style={[styles.appleButton, busy && styles.dim]}
                onPress={() => {
                  if (!busy) void continueWith("apple", signInWithApple);
                }}
              />
            )
          ) : null}

          {googleAvailable ? (
            <Pressable
              style={[styles.googleButton, busy && styles.dim]}
              onPress={() => void continueWith("google", signInWithGoogle)}
              disabled={busy}
              accessibilityRole="button"
              accessibilityLabel="Continue with Google"
            >
              {pending === "google" ? (
                <ActivityIndicator color={colors.textPrimary} />
              ) : (
                <>
                  <Icon name="logo-google" size={18} color={colors.textPrimary} />
                  <Text style={styles.googleText}>Continue with Google</Text>
                </>
              )}
            </Pressable>
          ) : null}

          {emailAvailable ? (
            <EmailCodeSignIn
              busy={busy && pending !== "email"}
              verifying={pending === "email"}
              onRequestCode={demo ? async () => undefined : requestEmailCode}
              onVerify={(email, code) =>
                void continueWith("email", () => verifyEmailCode(email, code))
              }
            />
          ) : null}

          {!anyProvider ? (
            <Text style={styles.notice}>
              Sign-in is being set up for this build. Please update Menivor or try again shortly.
            </Text>
          ) : null}

          {isDevBuild() ? (
            showKey ? (
              <View style={styles.keyBox}>
                <TextInput
                  style={styles.input}
                  value={keyValue}
                  onChangeText={setKeyValue}
                  placeholder="Access key (dev session)"
                  placeholderTextColor={colors.textFaint}
                  autoCapitalize="none"
                  autoCorrect={false}
                  secureTextEntry
                  editable={!busy}
                />
                <Pressable onPress={() => void signInWithKey()} disabled={busy} accessibilityRole="button">
                  <Text style={styles.link}>Use key</Text>
                </Pressable>
              </View>
            ) : (
              <Pressable onPress={() => setShowKey(true)} accessibilityRole="button">
                <Text style={styles.link}>Dev: sign in with an access key</Text>
              </Pressable>
            )
          ) : null}

          {error ? (
            <Text style={styles.error} accessibilityLiveRegion="polite">
              {error}
            </Text>
          ) : null}

          <View style={styles.legal}>
            <Text style={styles.legalNote}>Signing in creates your Menivor account. By continuing you agree to:</Text>
            <LegalLinks tint={colors.accent} mutedTint={colors.textFaint} />
          </View>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  center: { alignItems: "center", justifyContent: "center" },
  content: { flex: 1, paddingHorizontal: 20, justifyContent: "space-between" },
  brandRow: { flexDirection: "row", alignItems: "center", gap: 10, alignSelf: "center" },
  brandMark: {
    width: 28,
    height: 28,
    borderRadius: 9,
    backgroundColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
    paddingLeft: 2,
  },
  brand: { color: colors.textPrimary, fontSize: 20, fontWeight: "800", letterSpacing: -0.4 },
  panel: {
    gap: 12,
    padding: 22,
    borderRadius: 28,
    backgroundColor: "rgba(15,15,16,0.86)",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: "rgba(236,233,225,0.12)",
  },
  kicker: { ...kicker, fontSize: 11 },
  title: {
    color: colors.textPrimary,
    fontSize: 40,
    fontWeight: "800",
    letterSpacing: -1.4,
    lineHeight: 42,
  },
  subtitle: { color: colors.textSecondary, fontSize: 15, lineHeight: 22, marginBottom: 6 },
  primary: {
    minHeight: 52,
    borderRadius: 14,
    backgroundColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
  },
  primaryText: { color: colors.onAccent, fontSize: 16, fontWeight: "800" },
  appleButton: { height: 52, width: "100%" },
  providerBusy: {
    height: 52,
    borderRadius: 14,
    backgroundColor: colors.surfaceAlt,
    alignItems: "center",
    justifyContent: "center",
  },
  googleButton: {
    height: 52,
    borderRadius: 14,
    flexDirection: "row",
    gap: 10,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surfaceAlt,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  googleText: { color: colors.textPrimary, fontSize: 16, fontWeight: "700" },
  dim: { opacity: 0.5 },
  notice: { color: colors.textSecondary, fontSize: 13, lineHeight: 19, textAlign: "center" },
  keyBox: { gap: 8 },
  input: {
    minHeight: 46,
    paddingHorizontal: 12,
    borderRadius: 12,
    color: colors.textPrimary,
    backgroundColor: colors.input,
  },
  link: { color: colors.textSecondary, fontSize: 13, fontWeight: "600", textAlign: "center", textDecorationLine: "underline" },
  error: {
    color: colors.textPrimary,
    fontSize: 13,
    lineHeight: 18,
    padding: 10,
    borderRadius: 10,
    backgroundColor: "rgba(208,96,91,0.18)",
  },
  legal: { gap: 6, marginTop: 4 },
  legalNote: { color: colors.textFaint, fontSize: 11, lineHeight: 15, textAlign: "center" },
});
