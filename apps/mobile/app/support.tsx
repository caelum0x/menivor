import { useState } from "react";
import {
  Linking,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import Constants from "expo-constants";
import { Stack, useRouter } from "expo-router";

import { API_BASE } from "@/lib/api";
import { isRouteAvailable } from "@/src/shared/release/surface";
import { palette } from "@/src/shared/theme/tokens";
import { frameDepth } from "@/src/ui/menivor";

/**
 * Support contact. A build can point this at a help desk via
 * EXPO_PUBLIC_SUPPORT_URL (https:// or mailto:); otherwise it falls back to the
 * Menivor support inbox so the primary button always works in production.
 */
const DEFAULT_SUPPORT_URL = "mailto:hello@menivor.com?subject=Menivor%20app%20support";
const configuredSupportUrl = process.env.EXPO_PUBLIC_SUPPORT_URL?.trim() ?? "";
const supportUrl: string | null = /^(https?:\/\/|mailto:)/i.test(
  configuredSupportUrl,
)
  ? configuredSupportUrl
  : DEFAULT_SUPPORT_URL;

export default function SupportScreen() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  const openSupport = async () => {
    if (!supportUrl) return;
    setError(null);
    try {
      // openURL rejects when nothing can handle the link (e.g. no mail app),
      // which surfaces below with the address so the user can copy it.
      await Linking.openURL(supportUrl);
    } catch (reason) {
      setError(
        supportUrl.startsWith("mailto:")
          ? `No mail app is set up. Email ${supportUrl.slice(7).split("?")[0]} instead.`
          : reason instanceof Error
            ? reason.message
            : "Support could not be opened.",
      );
    }
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Stack.Screen options={{ title: "Support" }} />

      <Text style={styles.title}>Support</Text>
      <Text style={styles.intro}>
        Include the job ID and the exact failed stage or export receipt status
        when asking for help. Never send your sign-in details.
      </Text>

      <View style={styles.card}>
        <Text style={styles.label}>App version</Text>
        <Text selectable style={styles.value}>
          {Constants.expoConfig?.version ?? "Not reported"}
        </Text>
        <View style={styles.rule} />
        <Text style={styles.label}>API endpoint</Text>
        <Text selectable style={styles.value}>
          {API_BASE}
        </Text>
      </View>

      <Pressable
        style={[styles.primary, !supportUrl && styles.disabled]}
        disabled={!supportUrl}
        onPress={() => void openSupport()}
        accessibilityRole="link"
        accessibilityState={{ disabled: !supportUrl }}
      >
        <Text style={styles.primaryText}>
          {supportUrl ? "Contact support" : "Support contact not configured"}
        </Text>
      </Pressable>

      {isRouteAvailable("/account-access") ? (
        <Pressable
          style={styles.secondary}
          onPress={() => router.push("/account-access")}
          accessibilityRole="button"
        >
          <Text style={styles.secondaryText}>Account access help</Text>
        </Pressable>
      ) : null}
      <Pressable
        style={styles.secondary}
        onPress={() => router.push("/privacy")}
        accessibilityRole="button"
      >
        <Text style={styles.secondaryText}>Privacy and data controls</Text>
      </Pressable>

      {error ? <Text style={styles.error}>{error}</Text> : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: palette.ink },
  content: { padding: 20, paddingBottom: 48, gap: 14 },
  title: { color: palette.paper, fontSize: 32, fontWeight: "800", letterSpacing: -1 },
  intro: { color: palette.paperMuted, fontSize: 14, lineHeight: 21 },
  card: {
    backgroundColor: palette.surface,
    borderColor: palette.border,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: 18,
    padding: 18,
    gap: 9,
    boxShadow: frameDepth,
  },
  rule: { height: StyleSheet.hairlineWidth, backgroundColor: palette.border },
  label: { color: palette.paperMuted, fontSize: 11, fontWeight: "700", letterSpacing: 1.6, textTransform: "uppercase" },
  value: { color: palette.paper, fontFamily: "Menlo", fontSize: 12 },
  primary: {
    minHeight: 50,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: palette.accent,
    borderRadius: 16,
    paddingHorizontal: 14,
  },
  primaryText: { color: palette.accentInk, fontSize: 15, fontWeight: "800" },
  secondary: {
    minHeight: 48,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: palette.surfaceAlt,
    borderRadius: 16,
    paddingHorizontal: 14,
  },
  secondaryText: { color: palette.paper, fontSize: 14, fontWeight: "700" },
  disabled: { opacity: 0.45 },
  error: { color: palette.danger, fontSize: 13, lineHeight: 19 },
});
