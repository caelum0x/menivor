/**
 * Route: /r/[token] — a public reel share link opened in the app
 * (menivor://r/<token>, or https://menivor.com/r/<token> via universal / app
 * links). Resolves the token with the unauthenticated GET /public/r/{token} and
 * plays the watermarked preview; the payload never carries private fields.
 */

import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { Stack, useLocalSearchParams, useRouter } from "expo-router";

import { ApiError, getPublicShare } from "@/lib/api";
import type { SharePublic } from "@/lib/types";
import { useSession } from "@/src/shared/auth";
import { JobVideo } from "@/src/shared/media";
import { colors, radius, spacing, typeScale } from "@/src/shared/theme";

type LoadState =
  | { status: "loading" }
  | { status: "ready"; share: SharePublic }
  | { status: "missing" }
  | { status: "error"; message: string };

export default function PublicShareScreen() {
  const params = useLocalSearchParams<{ token?: string | string[] }>();
  const token = (Array.isArray(params.token) ? params.token[0] : params.token) ?? "";
  const { apiKey } = useSession();
  const router = useRouter();
  const [state, setState] = useState<LoadState>({ status: "loading" });

  const load = useCallback(async () => {
    if (!token.trim()) {
      setState({ status: "missing" });
      return;
    }
    setState({ status: "loading" });
    try {
      setState({ status: "ready", share: await getPublicShare(token.trim()) });
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setState({ status: "missing" });
        return;
      }
      setState({
        status: "error",
        message:
          err instanceof ApiError
            ? err.message
            : "Could not load this reel. Check your connection and try again.",
      });
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  const onMakeYourOwn = () => {
    router.replace(apiKey ? "/(tabs)/create" : "/");
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Stack.Screen options={{ title: "Shared reel", headerShown: true }} />
      {state.status === "loading" ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.accent} size="large" />
        </View>
      ) : state.status === "missing" ? (
        <View style={styles.card}>
          <Text style={styles.title}>This link is no longer available</Text>
          <Text style={styles.body}>
            The creator may have revoked it, or the reel was removed.
          </Text>
        </View>
      ) : state.status === "error" ? (
        <View style={styles.card}>
          <Text style={styles.title}>Could not load this reel</Text>
          <Text style={styles.body}>{state.message}</Text>
          <Pressable
            style={styles.secondary}
            onPress={() => void load()}
            accessibilityRole="button"
          >
            <Text style={styles.secondaryText}>Try again</Text>
          </Pressable>
        </View>
      ) : (
        <>
          <Text style={styles.title}>{state.share.title || "Untitled reel"}</Text>
          {state.share.created_at ? (
            <Text style={styles.meta}>
              {new Date(state.share.created_at).toLocaleDateString()}
            </Text>
          ) : null}
          <JobVideo uri={state.share.watermarked_preview_url} isLooping />
        </>
      )}

      <Pressable
        style={styles.primary}
        onPress={onMakeYourOwn}
        accessibilityRole="button"
      >
        <Text style={styles.primaryText}>Make your own reel</Text>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.xl, gap: spacing.md },
  center: { paddingVertical: 80, alignItems: "center" },
  card: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.lg,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  title: { color: colors.textPrimary, fontSize: typeScale.heading, fontWeight: "800" },
  body: { color: colors.textSecondary, fontSize: typeScale.body, lineHeight: 21 },
  meta: { color: colors.textFaint, fontSize: typeScale.caption },
  primary: {
    backgroundColor: colors.accent,
    borderRadius: radius.md,
    paddingVertical: 14,
    alignItems: "center",
    marginTop: spacing.sm,
  },
  primaryText: { color: colors.onAccent, fontSize: typeScale.body, fontWeight: "700" },
  secondary: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingVertical: 12,
    alignItems: "center",
  },
  secondaryText: { color: colors.textPrimary, fontSize: typeScale.body, fontWeight: "600" },
});
