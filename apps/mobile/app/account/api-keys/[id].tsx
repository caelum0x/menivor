/**
 * Account · API Key Detail
 *
 * Nav manifest: { route: "/account/api-keys/[id]", title: "API Key" }
 *
 * A single personal API key, resolved from GET /api/v1/me/api-keys by its row
 * id and joined with its current-month usage from GET /api/v1/me/api-keys/usage.
 * There is no single-key GET, so the screen loads both lists and finds the
 * matching rows. Shows the key's metadata (prefix — copyable —, created / last
 * used, status, rate limit + monthly quota), a usage-history card for the
 * current period, and a Revoke action (DELETE /api/v1/me/api-keys/{key_id})
 * behind a confirmation. Explicit loading / error / not-found states.
 *
 * Wires endpoints: GET /api/v1/me/api-keys, GET /api/v1/me/api-keys/usage,
 * DELETE /api/v1/me/api-keys/{key_id}.
 */

import { useCallback, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { Stack, useLocalSearchParams, useRouter } from "expo-router";

import { getApiKeyUsage, listApiKeys, revokeApiKey } from "@/lib/api";
import type { ApiKey, ApiKeyUsage } from "@/lib/types";
import { useSession } from "@/src/shared/auth";

import { DetailRows, type DetailRow } from "@/components/account/DetailRows";
import { formatDate, formatLastUsed } from "@/components/apikeys/format";
import { describeError } from "@/components/me/errors";
import { formatCount } from "@/components/me/format";
import { colors } from "@/components/me/theme";
import { StudioScreen } from "@/components/studio/StudioScreen";
import { useResource } from "@/components/me/use-resource";
import { UsageCard } from "@/components/usage/UsageCard";

function firstParam(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return value[0] ?? "";
  return value ?? "";
}

interface KeyDetailBundle {
  keys: ApiKey[];
  usage: ApiKeyUsage[];
}

async function fetchBundle(
  token: string | undefined,
): Promise<KeyDetailBundle> {
  const [keys, usage] = await Promise.all([
    listApiKeys({ token }),
    getApiKeyUsage({ token }).catch(() => [] as ApiKeyUsage[]),
  ]);
  return { keys, usage };
}

/** Human label for a per-minute rate limit (null/0 → the plan default). */
function rateLimitLabel(value: number | null | undefined): string {
  if (typeof value === "number" && Number.isFinite(value) && value > 0) {
    return `${formatCount(value)} req/min`;
  }
  return "Plan default";
}

function quotaLabel(value: number | null | undefined): string {
  if (typeof value === "number" && Number.isFinite(value) && value > 0) {
    return `${formatCount(value)} req/month`;
  }
  return "Unlimited";
}

export default function AccountApiKeyDetailScreen() {
  const { apiKey: sessionKey } = useSession();
  const token = sessionKey ?? undefined;
  const router = useRouter();
  const params = useLocalSearchParams<{ id?: string | string[] }>();
  const id = firstParam(params.id).trim();

  const fetcher = useCallback(() => fetchBundle(token), [token]);
  const { status, data, error, reload } = useResource<KeyDetailBundle>(fetcher);
  const [revoking, setRevoking] = useState(false);

  const key = useMemo(
    () => (data?.keys ?? []).find((k) => k.id === id) ?? null,
    [data, id],
  );
  const usage = useMemo(
    () => (data?.usage ?? []).find((u) => u.id === id) ?? null,
    [data, id],
  );

  const rows: DetailRow[] = useMemo(() => {
    if (!key) return [];
    const out: DetailRow[] = [
      { label: "Prefix", value: key.prefix ? `${key.prefix}…` : "—", copyable: !!key.prefix, mono: true },
      { label: "Status", value: key.revoked ? "Revoked" : "Active" },
      { label: "Last used", value: formatLastUsed(key.last_used_at) },
    ];
    const created = formatDate(key.created_at);
    if (created) out.push({ label: "Created", value: created });
    out.push({ label: "Rate limit", value: rateLimitLabel(key.rate_limit_per_min) });
    out.push({ label: "Monthly quota", value: quotaLabel(key.monthly_quota) });
    return out;
  }, [key]);

  const doRevoke = useCallback(async () => {
    setRevoking(true);
    try {
      await revokeApiKey(id, { token });
      router.back();
    } catch (err) {
      setRevoking(false);
      Alert.alert(
        "Couldn’t revoke",
        describeError(err, "Failed to revoke this key."),
      );
    }
  }, [id, token, router]);

  const onRevoke = useCallback(() => {
    Alert.alert(
      "Revoke this API key?",
      "Any integration using it will immediately stop working. This can’t be undone.",
      [
        { text: "Keep", style: "cancel" },
        { text: "Revoke", style: "destructive", onPress: () => void doRevoke() },
      ],
      { cancelable: true },
    );
  }, [doRevoke]);

  const name = key ? key.name || "Untitled key" : "API Key";

  return (
    <StudioScreen
      status={status}
      error={error}
      onRetry={reload}
      loadingLabel="Loading key…"
    >
      <Stack.Screen options={{ title: name }} />
      {!key ? (
        <View style={styles.notFound}>
          <Text style={styles.notFoundTitle}>Key not found</Text>
          <Text style={styles.notFoundText}>
            This key is no longer on your account. It may have been revoked and
            removed.
          </Text>
          <Pressable
            style={styles.secondary}
            onPress={() => router.back()}
            accessibilityRole="button"
          >
            <Text style={styles.secondaryText}>Back to keys</Text>
          </Pressable>
        </View>
      ) : (
        <ScrollView contentContainerStyle={styles.content}>
          <Text style={styles.title}>{name}</Text>

          <DetailRows rows={rows} />

          <Text style={styles.sectionLabel}>THIS MONTH</Text>
          {usage ? (
            <UsageCard usage={usage} />
          ) : (
            <Text style={styles.noUsage}>
              No requests recorded for this key in the current month yet.
            </Text>
          )}

          {key.revoked ? (
            <Text style={styles.revokedNote}>
              This key has been revoked and can no longer authenticate.
            </Text>
          ) : (
            <Pressable
              style={styles.revoke}
              onPress={onRevoke}
              disabled={revoking}
              accessibilityRole="button"
              accessibilityState={{ disabled: revoking }}
            >
              {revoking ? (
                <ActivityIndicator color={colors.error} size="small" />
              ) : (
                <Text style={styles.revokeText}>Revoke key</Text>
              )}
            </Pressable>
          )}
        </ScrollView>
      )}
    </StudioScreen>
  );
}

const styles = StyleSheet.create({
  content: { padding: 16, paddingBottom: 48, gap: 16 },
  title: { color: colors.textPrimary, fontSize: 22, fontWeight: "800" },
  sectionLabel: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 1.2,
  },
  noUsage: { color: colors.textSecondary, fontSize: 13, lineHeight: 18 },
  revoke: {
    borderColor: colors.error,
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 13,
    alignItems: "center",
  },
  revokeText: { color: colors.error, fontSize: 15, fontWeight: "700" },
  revokedNote: {
    color: colors.muted,
    fontSize: 13,
    lineHeight: 18,
    fontStyle: "italic",
  },
  notFound: {
    flex: 1,
    padding: 24,
    gap: 12,
    alignItems: "center",
    justifyContent: "center",
  },
  notFoundTitle: { color: colors.textPrimary, fontSize: 18, fontWeight: "700" },
  notFoundText: {
    color: colors.textSecondary,
    fontSize: 14,
    lineHeight: 20,
    textAlign: "center",
  },
  secondary: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
  secondaryText: { color: colors.textSecondary, fontSize: 14, fontWeight: "600" },
});
