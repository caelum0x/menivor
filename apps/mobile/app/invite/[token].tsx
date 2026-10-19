/**
 * Route: /invite/[token] — accept a team workspace invite. Opened from the
 * shareable link (https://menivor.com/invite/<token>, an associated domain) or
 * in-app. Previews the invite (GET /invites/{token}); a signed-out user is sent
 * to sign in and brought back here; a signed-in user joins with
 * POST /invites/{token}/accept and lands on the team screen.
 */

import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import { Stack, useLocalSearchParams, useRouter } from "expo-router";

import { Icon } from "@/components/ui/Icon";
import { roleLabel } from "@/components/team/roles";
import { ApiError } from "@/src/shared/api";
import { useSession } from "@/src/shared/auth";
import { colors, radius, spacing, typeScale } from "@/src/shared/theme";
import { acceptInvite, getInvite, type InvitePreview } from "@/lib/invites";

function describe(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 404) return "This invite link is invalid or was revoked.";
    if (err.status === 410) return "This invite has expired. Ask for a new link.";
    if (err.status === 409) return "You're already a member of this workspace.";
    if (err.status === 403) return "This invite was sent to a different email address.";
    return err.message;
  }
  return err instanceof Error ? err.message : "Something went wrong.";
}

export default function AcceptInviteScreen() {
  const { token: rawToken } = useLocalSearchParams<{ token: string }>();
  const token = typeof rawToken === "string" ? rawToken : "";
  const { apiKey, loading: sessionLoading } = useSession();
  const router = useRouter();

  const [preview, setPreview] = useState<InvitePreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [accepting, setAccepting] = useState(false);
  const [joined, setJoined] = useState(false);

  useEffect(() => {
    if (!token) {
      setError("This invite link is missing its token.");
      setLoading(false);
      return;
    }
    let active = true;
    setLoading(true);
    getInvite(token, { token: apiKey ?? undefined })
      .then((result) => {
        if (active) setPreview(result);
      })
      .catch((err) => {
        if (active) setError(describe(err));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [apiKey, token]);

  const onAccept = useCallback(async () => {
    if (!apiKey || accepting) return;
    setAccepting(true);
    setError(null);
    try {
      await acceptInvite(token, { token: apiKey });
      setJoined(true);
    } catch (err) {
      setError(describe(err));
    } finally {
      setAccepting(false);
    }
  }, [accepting, apiKey, token]);

  const onSignIn = useCallback(() => {
    router.push({ pathname: "/", params: { next: `/invite/${token}` } });
  }, [router, token]);

  const closed = preview && preview.status !== "pending";

  return (
    <View style={styles.container}>
      <Stack.Screen options={{ title: "Team invite" }} />
      {loading || sessionLoading ? (
        <ActivityIndicator color={colors.accent} size="large" />
      ) : (
        <View style={styles.card}>
          <Icon name="people-outline" size={36} color={colors.accent} />
          {preview ? (
            <>
              <Text style={styles.title}>Join {preview.workspaceName}</Text>
              <Text style={styles.meta}>
                {roleLabel(preview.role)} access
                {preview.invitedBy ? ` · invited by ${preview.invitedBy}` : ""}
              </Text>
              {preview.email ? <Text style={styles.meta}>Sent to {preview.email}</Text> : null}
            </>
          ) : (
            <Text style={styles.title}>Team invite</Text>
          )}

          {joined ? (
            <>
              <Text style={styles.success}>You joined the workspace.</Text>
              <Pressable style={styles.primary} onPress={() => router.replace("/account/workspaces/members")} accessibilityRole="button">
                <Text style={styles.primaryText}>Open team</Text>
              </Pressable>
            </>
          ) : closed ? (
            <Text style={styles.error}>This invite is {preview?.status} and can no longer be used.</Text>
          ) : preview && !apiKey ? (
            <>
              <Text style={styles.body}>Sign in or create your account, then you'll come back here to join.</Text>
              <Pressable style={styles.primary} onPress={onSignIn} accessibilityRole="button">
                <Text style={styles.primaryText}>Sign in to accept</Text>
              </Pressable>
            </>
          ) : preview ? (
            <Pressable
              style={[styles.primary, accepting && styles.disabled]}
              onPress={() => void onAccept()}
              disabled={accepting}
              accessibilityRole="button"
              accessibilityLabel={`Accept invite to ${preview.workspaceName}`}
            >
              {accepting ? (
                <ActivityIndicator color={colors.onAccent} />
              ) : (
                <Text style={styles.primaryText}>Accept invite</Text>
              )}
            </Pressable>
          ) : null}

          {error ? <Text style={styles.error}>{error}</Text> : null}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bg,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.xl,
  },
  card: {
    width: "100%",
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.lg,
    padding: spacing.xl,
    alignItems: "center",
    gap: spacing.md,
  },
  title: { color: colors.textPrimary, fontSize: typeScale.heading, fontWeight: "800", textAlign: "center" },
  meta: { color: colors.textSecondary, fontSize: typeScale.caption, textAlign: "center" },
  body: { color: colors.textSecondary, fontSize: typeScale.body, textAlign: "center" },
  success: { color: colors.success, fontSize: typeScale.body, fontWeight: "700" },
  error: { color: colors.danger, fontSize: typeScale.caption, textAlign: "center" },
  primary: {
    alignSelf: "stretch",
    backgroundColor: colors.accent,
    borderRadius: radius.md,
    paddingVertical: spacing.md,
    alignItems: "center",
  },
  primaryText: { color: colors.onAccent, fontSize: typeScale.body, fontWeight: "700" },
  disabled: { opacity: 0.5 },
});
