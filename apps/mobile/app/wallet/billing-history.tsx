/**
 * Route: /wallet/billing-history — a workspace's invoices and metered usage.
 *
 * Pick a workspace, then see this period's metered usage vs plan limits and the
 * full invoice history (newest first) with expandable line items. Wired to:
 *   - GET /workspaces                        → listMyWorkspaces
 *   - GET /me/workspaces/{id}/usage          → getWorkspaceUsage
 *   - GET /me/workspaces/{id}/invoices       → listWorkspaceInvoices
 *
 * Invoice amounts are server-authoritative integer cents (never a float);
 * usage/overage are integer units. Invoice listing is `billing.manage`-gated —
 * a 403 downgrades the invoices section to a notice rather than crashing. All
 * reads are tenant-scoped server-side; no secrets live here.
 */

import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { useFocusEffect } from "expo-router";

import { colors } from "@/components/me/theme";
import { useSession } from "@/src/shared/auth";
import { ApiError } from "@/src/shared/api";
import { listMyWorkspaces } from "@/lib/api";
import type { Workspace } from "@/lib/types";
import {
  getWorkspaceUsage,
  listWorkspaceInvoices,
  type Invoice,
  type Usage,
} from "@/lib/billing";
import { featureLabel, formatInt, formatPeriod, metricRatio } from "@/components/billing/plan-format";
import { WorkspacePicker } from "@/components/wallet/WorkspacePicker";
import { formatCents, formatDate, formatStatus } from "@/components/wallet/format";

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return fallback;
}

export default function WalletBillingHistoryScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const [workspaces, setWorkspaces] = useState<readonly Workspace[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [invoices, setInvoices] = useState<readonly Invoice[]>([]);
  const [invoicesGated, setInvoicesGated] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const [loadingWorkspaces, setLoadingWorkspaces] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadWorkspaces = useCallback(async () => {
    setError(null);
    try {
      const rows = await listMyWorkspaces({ token });
      setWorkspaces(rows);
      setSelectedId((current) => current ?? rows[0]?.id ?? null);
    } catch (err) {
      setError(errorMessage(err, "Failed to load your workspaces."));
    }
  }, [token]);

  useFocusEffect(
    useCallback(() => {
      let active = true;
      setLoadingWorkspaces(true);
      loadWorkspaces().finally(() => {
        if (active) setLoadingWorkspaces(false);
      });
      return () => {
        active = false;
      };
    }, [loadWorkspaces]),
  );

  const loadDetail = useCallback(
    async (workspaceId: string) => {
      setError(null);
      setLoadingDetail(true);
      setInvoicesGated(false);
      try {
        const [use, inv] = await Promise.all([
          getWorkspaceUsage(workspaceId, undefined, { token }),
          listWorkspaceInvoices(workspaceId, { token }).catch((err) => {
            if (err instanceof ApiError && err.status === 403) {
              setInvoicesGated(true);
              return [] as Invoice[];
            }
            throw err;
          }),
        ]);
        setUsage(use);
        setInvoices(inv);
      } catch (err) {
        setError(errorMessage(err, "Failed to load billing for this workspace."));
      } finally {
        setLoadingDetail(false);
      }
    },
    [token],
  );

  useEffect(() => {
    if (selectedId) void loadDetail(selectedId);
  }, [selectedId, loadDetail]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await loadWorkspaces();
    if (selectedId) await loadDetail(selectedId);
    setRefreshing(false);
  }, [loadWorkspaces, loadDetail, selectedId]);

  const toggle = useCallback((id: string) => {
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));
  }, []);

  if (loadingWorkspaces && workspaces.length === 0) {
    return (
      <View style={[styles.container, styles.center]}>
        <ActivityIndicator color={colors.primary} size="large" />
      </View>
    );
  }

  if (!loadingWorkspaces && workspaces.length === 0) {
    return (
      <ScrollView
        style={styles.container}
        contentContainerStyle={[styles.content, styles.center]}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />}
      >
        {error ? <Text style={styles.error}>{error}</Text> : null}
        <Text style={styles.emptyTitle}>No workspaces</Text>
        <Text style={styles.emptyBody}>
          Invoices and usage belong to a team workspace. Create one from the Team
          screen to see billing history.
        </Text>
      </ScrollView>
    );
  }

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />}
    >
      <WorkspacePicker
        workspaces={workspaces}
        selectedId={selectedId}
        onSelect={(id) => setSelectedId(id)}
      />

      {error ? <Text style={styles.error}>{error}</Text> : null}

      {loadingDetail && !usage ? (
        <ActivityIndicator color={colors.primary} style={styles.detailSpinner} />
      ) : (
        <>
          {usage ? (
            <View style={styles.card}>
              <Text style={styles.sectionTitle}>
                Usage {usage.period ? `· ${formatPeriod(usage.period)}` : ""}
              </Text>
              {usage.overage.length === 0 ? (
                <Text style={styles.muted}>No metered usage recorded this period.</Text>
              ) : (
                usage.overage.map((m) => {
                  const ratio = metricRatio(m.used, m.limit);
                  return (
                    <View key={m.metric} style={styles.usageRow}>
                      <View style={styles.usageHead}>
                        <Text style={styles.usageMetric}>{featureLabel(m.metric)}</Text>
                        <Text style={styles.usageCount}>
                          {formatInt(m.used)}
                          {m.limit !== null ? ` / ${formatInt(m.limit)}` : " · unlimited"}
                        </Text>
                      </View>
                      {ratio !== null ? (
                        <View style={styles.track}>
                          <View
                            style={[
                              styles.fill,
                              { width: `${Math.round(ratio * 100)}%` },
                              m.overage > 0 && styles.fillOver,
                            ]}
                          />
                        </View>
                      ) : null}
                      {m.overage > 0 ? (
                        <Text style={styles.overage}>{formatInt(m.overage)} over allotment</Text>
                      ) : null}
                    </View>
                  );
                })
              )}
            </View>
          ) : null}

          <Text style={styles.sectionTitle}>Invoices</Text>
          {invoicesGated ? (
            <Text style={styles.muted}>
              You need the billing role to view this workspace&apos;s invoices.
            </Text>
          ) : invoices.length === 0 ? (
            <Text style={styles.muted}>No invoices yet.</Text>
          ) : (
            invoices.map((inv) => {
              const open = expanded[inv.id] ?? false;
              return (
                <View key={inv.id} style={styles.card}>
                  <Pressable
                    style={styles.invoiceHead}
                    onPress={() => toggle(inv.id)}
                    accessibilityRole="button"
                    accessibilityState={{ expanded: open }}
                  >
                    <View style={styles.invoiceLeft}>
                      <Text style={styles.invoiceAmount}>
                        {formatCents(inv.amount_cents, inv.currency)}
                      </Text>
                      <Text style={styles.invoiceMeta}>
                        {formatStatus(inv.status)}
                        {inv.period_start ? ` · ${formatDate(inv.period_start)}` : ""}
                      </Text>
                    </View>
                    <Text style={styles.chevron}>{open ? "Hide" : "Details"}</Text>
                  </Pressable>
                  {open ? (
                    <View style={styles.lines}>
                      {inv.line_items.length === 0 ? (
                        <Text style={styles.muted}>No line items.</Text>
                      ) : (
                        inv.line_items.map((line) => (
                          <View key={line.id} style={styles.lineRow}>
                            <Text style={styles.lineDesc} numberOfLines={2}>
                              {line.description}
                              {line.quantity > 1 ? `  ×${line.quantity}` : ""}
                            </Text>
                            <Text style={styles.lineAmount}>
                              {formatCents(line.amount_cents, inv.currency)}
                            </Text>
                          </View>
                        ))
                      )}
                    </View>
                  ) : null}
                </View>
              );
            })
          )}
        </>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20, paddingBottom: 48 },
  center: { flexGrow: 1, alignItems: "center", justifyContent: "center" },
  error: { color: colors.error, fontSize: 14, marginTop: 14 },
  detailSpinner: { marginTop: 32 },
  card: {
    marginTop: 14,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 14,
    padding: 16,
  },
  sectionTitle: {
    color: colors.textPrimary,
    fontSize: 16,
    fontWeight: "700",
    marginTop: 22,
    marginBottom: 2,
  },
  muted: { color: colors.textSecondary, fontSize: 14, marginTop: 10 },
  usageRow: { marginTop: 14 },
  usageHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: 12 },
  usageMetric: { color: colors.textPrimary, fontSize: 14, fontWeight: "500", flexShrink: 1 },
  usageCount: { color: colors.textSecondary, fontSize: 13 },
  track: {
    marginTop: 8,
    height: 7,
    borderRadius: 4,
    backgroundColor: colors.cardAlt,
    overflow: "hidden",
  },
  fill: { height: 7, borderRadius: 4, backgroundColor: colors.primary },
  fillOver: { backgroundColor: colors.error },
  overage: { color: colors.error, fontSize: 12, marginTop: 5 },
  invoiceHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: 12 },
  invoiceLeft: { flexShrink: 1 },
  invoiceAmount: { color: colors.textPrimary, fontSize: 18, fontWeight: "700" },
  invoiceMeta: { color: colors.textSecondary, fontSize: 13, marginTop: 3 },
  chevron: { color: colors.primary, fontSize: 14, fontWeight: "600" },
  lines: { marginTop: 14, borderTopWidth: 1, borderTopColor: colors.border, paddingTop: 12, gap: 10 },
  lineRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start", gap: 12 },
  lineDesc: { color: colors.textSecondary, fontSize: 13, flex: 1 },
  lineAmount: { color: colors.textPrimary, fontSize: 13, fontWeight: "600" },
  emptyTitle: { color: colors.textPrimary, fontSize: 18, fontWeight: "700", marginBottom: 8 },
  emptyBody: {
    color: colors.textSecondary,
    fontSize: 14,
    lineHeight: 21,
    textAlign: "center",
    paddingHorizontal: 20,
  },
});
