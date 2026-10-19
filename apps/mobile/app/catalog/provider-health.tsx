/**
 * Provider Health — GET /catalog/providers/health.
 *
 * Live rolling uptime, average latency, and derived state for every provider
 * observed in the selected window. Switch the window (1h / 24h / 7d / 30d) to
 * re-query. Read-only status surface.
 *
 * Route: /catalog/provider-health
 */

import type { ReactElement } from "react";
import { useCallback, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors } from "@/components/me/theme";
import { CatalogList } from "@/components/catalog/CatalogList";
import { HealthBadge } from "@/components/catalog/HealthBadge";
import { useCatalogResource } from "@/components/catalog/use-catalog-resource";
import { useSession } from "@/src/shared/auth";
import { getProviderHealth, type ProviderHealth } from "@/lib/marketplace";

const WINDOWS: readonly { hours: number; label: string }[] = [
  { hours: 1, label: "1h" },
  { hours: 24, label: "24h" },
  { hours: 168, label: "7d" },
  { hours: 720, label: "30d" },
];

function latencyLabel(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

export default function ProviderHealthScreen(): ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const [windowH, setWindowH] = useState<number>(24);

  const fetcher = useCallback(
    () => getProviderHealth({ token }, windowH),
    [token, windowH],
  );
  const { status, data, error, refreshing, reload, refresh } =
    useCatalogResource<ProviderHealth[]>(fetcher);

  const items = data ?? [];

  const renderItem = useCallback((provider: ProviderHealth): ReactElement => {
    return (
      <View style={styles.card}>
        <View style={styles.cardHead}>
          <Text style={styles.name} numberOfLines={1}>
            {provider.provider_key}
          </Text>
          <HealthBadge
            state={provider.state}
            uptime={provider.uptime}
            samples={provider.samples}
          />
        </View>
        <View style={styles.metrics}>
          <View style={styles.metric}>
            <Text style={styles.metricValue}>
              {provider.samples > 0 ? `${Math.round(provider.uptime * 100)}%` : "—"}
            </Text>
            <Text style={styles.metricLabel}>Uptime</Text>
          </View>
          <View style={styles.metric}>
            <Text style={styles.metricValue}>{latencyLabel(provider.avg_latency_ms)}</Text>
            <Text style={styles.metricLabel}>Avg latency</Text>
          </View>
          <View style={styles.metric}>
            <Text style={styles.metricValue}>{provider.samples}</Text>
            <Text style={styles.metricLabel}>Samples</Text>
          </View>
        </View>
      </View>
    );
  }, []);

  const header = (
    <View style={styles.windowRow}>
      {WINDOWS.map((w) => {
        const active = w.hours === windowH;
        return (
          <Pressable
            key={w.hours}
            onPress={() => setWindowH(w.hours)}
            style={[styles.windowBtn, active && styles.windowBtnActive]}
            accessibilityRole="button"
          >
            <Text style={[styles.windowText, active && styles.windowTextActive]}>{w.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );

  return (
    <CatalogList<ProviderHealth>
      status={status}
      error={error}
      items={items}
      keyExtractor={(p) => p.provider_key}
      renderItem={renderItem}
      onRetry={reload}
      refreshing={refreshing}
      onRefresh={refresh}
      intro="Live provider reliability from real generation runs. Uptime, average latency, and a derived state per provider over the chosen window."
      header={header}
      emptyTitle="No provider data yet"
      emptyBody="No providers reported a run in this window. Try a longer window or pull to refresh."
      loadingLabel="Loading provider health…"
    />
  );
}

const styles = StyleSheet.create({
  windowRow: { flexDirection: "row", gap: 8, marginBottom: 12 },
  windowBtn: {
    flex: 1,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 8,
    alignItems: "center",
  },
  windowBtnActive: { backgroundColor: colors.accent, borderColor: colors.accent },
  windowText: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  windowTextActive: { color: colors.bg, fontWeight: "700" },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 10,
    gap: 12,
  },
  cardHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 },
  name: { color: colors.textPrimary, fontSize: 15, fontWeight: "700", flex: 1 },
  metrics: { flexDirection: "row", justifyContent: "space-between" },
  metric: { alignItems: "center", flex: 1, gap: 2 },
  metricValue: { color: colors.textPrimary, fontSize: 16, fontWeight: "700" },
  metricLabel: { color: colors.muted, fontSize: 11, textTransform: "uppercase", letterSpacing: 1 },
});
