/**
 * API usage manager: lists the caller's per-key current-month request usage +
 * limits (GET /me/api-keys/usage, POWER-USER TIER quotas) with the shared
 * loading / error / retry treatment and a manual refresh.
 *
 * Read-only + strictly caller-scoped by the backend; the payload NEVER carries a
 * raw key or hash (only the safe `prefix`). Auth flows through the shared
 * `x-api-key` token — no secrets live here.
 */

import { useCallback } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { getApiKeyUsage } from "@/lib/api";
import type { ApiKeyUsage } from "@/lib/types";

import { Section, SectionState } from "@/components/me/Section";
import { colors } from "@/components/me/theme";
import { useResource } from "@/components/me/use-resource";

import { UsageCard } from "./UsageCard";

interface UsageManagerProps {
  token: string | undefined;
}

export function UsageManager({ token }: UsageManagerProps) {
  const fetcher = useCallback(() => getApiKeyUsage({ token }), [token]);
  const { status, data, error, reload } = useResource<ApiKeyUsage[]>(fetcher);

  const rows = data ?? [];

  return (
    <Section
      title="API USAGE"
      action={
        <Pressable onPress={reload} hitSlop={8} accessibilityRole="button">
          <Text style={styles.refresh}>Refresh</Text>
        </Pressable>
      }
    >
      <SectionState
        status={status}
        error={error}
        onRetry={reload}
        loadingLabel="Loading usage…"
      >
        {rows.length === 0 ? (
          <Text style={styles.empty}>
            No API keys yet. Create a key above to start tracking
            its monthly request usage here.
          </Text>
        ) : (
          <View style={styles.list}>
            {rows.map((usage) => (
              <UsageCard key={usage.id} usage={usage} />
            ))}
          </View>
        )}
      </SectionState>
    </Section>
  );
}

const styles = StyleSheet.create({
  refresh: { color: colors.accent, fontWeight: "600", fontSize: 13 },
  list: { gap: 10 },
  empty: {
    color: colors.muted,
    fontSize: 13,
    lineHeight: 18,
    paddingVertical: 8,
  },
});
