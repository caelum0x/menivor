import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { Stack, useRouter } from "expo-router";

import { createDeviceSession, isAbortError, me } from "@/lib/api";
import { getOrCreateInstallId, useSession } from "@/src/shared/auth";

export default function AccountAccessScreen() {
  const { apiKey, signIn, signOut } = useSession();
  const router = useRouter();
  const token = apiKey ?? undefined;
  const [userId, setUserId] = useState<string | null>(null);
  const [recovering, setRecovering] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    me({ token, signal: controller.signal })
      .then((profile) => setUserId(profile.user_id || null))
      .catch((reason: unknown) => {
        if (!isAbortError(reason)) setError("Account details are unavailable.");
      });
    return () => controller.abort();
  }, [token]);

  const restoreDeviceAccount = async () => {
    setRecovering(true);
    setError(null);
    setMessage(null);
    try {
      const installId = await getOrCreateInstallId();
      const platform = Platform.OS === "android" ? "android" : "ios";
      const session = await createDeviceSession(installId, platform);
      await signIn(session.api_key);
      setUserId(session.user_id);
      setMessage(
        session.created
          ? "A device account was created and secured on this installation."
          : "This installation's device account was restored.",
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The device account could not be restored.",
      );
    } finally {
      setRecovering(false);
    }
  };

  const switchToApiKey = async () => {
    await signOut();
    router.replace("/");
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Stack.Screen options={{ title: "Account access" }} />

      <Text style={styles.title}>Account access</Text>
      <Text style={styles.intro}>
        Menivor can restore the account tied to this app installation without
        asking you to copy an API key.
      </Text>

      <View style={styles.card}>
        <Text style={styles.label}>Current account</Text>
        <Text selectable style={styles.userId}>
          {userId ?? "Loading account ID"}
        </Text>
        <Text style={styles.body}>
          Device recovery works on this installation. Deleting the app or moving
          to another device may remove the secure installation identifier.
        </Text>
        <Pressable
          style={[styles.primary, recovering && styles.disabled]}
          disabled={recovering}
          onPress={() => void restoreDeviceAccount()}
          accessibilityRole="button"
          accessibilityState={{ busy: recovering, disabled: recovering }}
        >
          {recovering ? (
            <ActivityIndicator color="#ffffff" />
          ) : (
            <Text style={styles.primaryText}>Restore this device account</Text>
          )}
        </Pressable>
      </View>

      <View style={styles.card}>
        <Text style={styles.label}>Existing API key</Text>
        <Text style={styles.body}>
          Sign out to enter a Menivor API key for a different account. Keep
          that key in your own password manager; Menivor cannot display it
          after sign-in.
        </Text>
        <Pressable
          style={styles.secondary}
          onPress={() => void switchToApiKey()}
          accessibilityRole="button"
        >
          <Text style={styles.secondaryText}>Sign in with another API key</Text>
        </Pressable>
      </View>

      {message ? <Text style={styles.success}>{message}</Text> : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#f7f7f8" },
  content: { padding: 20, paddingBottom: 48, gap: 16 },
  title: {
    color: "#171717",
    fontFamily: "Helvetica Neue",
    fontSize: 32,
    fontWeight: "700",
    letterSpacing: -1,
  },
  intro: {
    color: "#646469",
    fontFamily: "Helvetica Neue",
    fontSize: 14,
    lineHeight: 21,
  },
  card: {
    backgroundColor: "#ffffff",
    borderColor: "#d8d8dc",
    borderWidth: 1,
    padding: 18,
    gap: 12,
  },
  label: {
    color: "#171717",
    fontFamily: "Helvetica Neue",
    fontSize: 13,
    fontWeight: "700",
  },
  userId: { color: "#002fa7", fontFamily: "Menlo", fontSize: 11 },
  body: {
    color: "#646469",
    fontFamily: "Helvetica Neue",
    fontSize: 13,
    lineHeight: 19,
  },
  primary: {
    minHeight: 46,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#002fa7",
    paddingHorizontal: 14,
  },
  primaryText: {
    color: "#ffffff",
    fontFamily: "Helvetica Neue",
    fontSize: 13,
    fontWeight: "700",
  },
  secondary: {
    minHeight: 46,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#ffffff",
    borderColor: "#002fa7",
    borderWidth: 1,
    paddingHorizontal: 14,
  },
  secondaryText: {
    color: "#002fa7",
    fontFamily: "Helvetica Neue",
    fontSize: 13,
    fontWeight: "700",
  },
  disabled: { opacity: 0.45 },
  success: { color: "#002fa7", fontSize: 13, lineHeight: 19 },
  error: { color: "#e4002b", fontSize: 13, lineHeight: 19 },
});
