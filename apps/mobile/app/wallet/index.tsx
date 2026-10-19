/**
 * Route: /wallet/ — Wallet & billing hub.
 *
 * NAV MANIFEST (for the integration agent — add these routes+titles):
 *   { route: "/wallet",                 title: "Wallet" }
 *   { route: "/wallet/history",         title: "Transactions" }
 *   { route: "/wallet/top-up",          title: "Add credit" }
 *   { route: "/wallet/transfer",        title: "Send tokens" }
 *   { route: "/wallet/transfer-policy", title: "Send limits" }
 *   { route: "/wallet/plans",           title: "Plans" }
 *   { route: "/wallet/billing-history", title: "Billing history" }
 *
 * The dashboard is the single wallet landing surface: it shows the live USD
 * balance (available + reserved), this period's spend against the monthly
 * budget, a recent-activity preview and a grid of actions that deep-link to the
 * rest of the cluster. Wired to real reads:
 *   - GET /wallet          → getWallet (balance snapshot)
 *   - GET /wallet/activity → getWalletActivity (recent ledger rows)
 *   - GET /spend/policy    → getSpendPolicy (budget cap + period spend)
 * Pull-to-refresh reloads all three. Auth flows through the shared client as
 * `x-api-key`; money is server-authoritative and only formatted here.
 */

import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { useFocusEffect, useRouter } from "expo-router";

import { colors } from "@/components/me/theme";
import { useSession } from "@/src/shared/auth";
import { ApiError } from "@/src/shared/api";
import { BalanceCard } from "@/src/features/wallet-publish";
import { ActivityLedger } from "@/src/features/wallet-publish";
import {
  formatUsdMicros,
  getSpendPolicy,
  getWallet,
  getWalletActivity,
  type SpendPolicy,
  type WalletActivityEntry,
  type WalletBalance,
} from "@/lib/marketplace";
import { isRouteAvailable } from "@/src/shared/release/surface";

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return fallback;
}

interface QuickAction {
  key: string;
  label: string;
  route: string;
  hint: string;
}

const QUICK_ACTIONS: readonly QuickAction[] = [
  { key: "topup", label: "Add credit", route: "/wallet/top-up", hint: "Top up your balance" },
  { key: "send", label: "Send tokens", route: "/wallet/transfer", hint: "Transfer to a handle" },
  { key: "limits", label: "Send limits", route: "/wallet/transfer-policy", hint: "Per-transfer & daily caps" },
  { key: "history", label: "Transactions", route: "/wallet/history", hint: "Full ledger" },
  { key: "plans", label: "Plans", route: "/wallet/plans", hint: "Subscription tiers" },
  { key: "billing", label: "Billing history", route: "/wallet/billing-history", hint: "Invoices & usage" },
  { key: "destinations", label: "Receive identities", route: "/wallet/destinations", hint: "Managed addresses" },
];

function budgetRatio(policy: SpendPolicy | null): number | null {
  if (!policy || policy.monthly_budget_micros <= 0) return null;
  const used = Math.max(0, policy.period_spend_micros);
  return Math.min(1, used / policy.monthly_budget_micros);
}

export default function WalletDashboardScreen() {
  const { apiKey } = useSession();
  const router = useRouter();
  const token = apiKey ?? undefined;

  const [balance, setBalance] = useState<WalletBalance | null>(null);
  const [policy, setPolicy] = useState<SpendPolicy | null>(null);
  const [recent, setRecent] = useState<readonly WalletActivityEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [snapshot, activity, spend] = await Promise.all([
        getWallet({ token }),
        getWalletActivity({ token }, 6),
        // Spend policy is optional context; a failure here shouldn't blank the
        // whole hub, so it is fetched defensively and downgraded to null.
        getSpendPolicy({ token }).catch(() => null),
      ]);
      setBalance(snapshot);
      setRecent(activity);
      setPolicy(spend);
    } catch (err) {
      setError(errorMessage(err, "Failed to load your wallet."));
    }
  }, [token]);

  useFocusEffect(
    useCallback(() => {
      let active = true;
      setLoading(true);
      load().finally(() => {
        if (active) setLoading(false);
      });
      return () => {
        active = false;
      };
    }, [load]),
  );

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  const ratio = budgetRatio(policy);

  if (loading && !balance) {
    return (
      <View style={[styles.container, styles.center]}>
        <ActivityIndicator color={colors.primary} size="large" />
      </View>
    );
  }

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />
      }
    >
      {error ? <Text style={styles.error}>{error}</Text> : null}

      <BalanceCard balance={balance} onTopUp={() => router.push("/wallet/top-up")} />

      {policy ? (
        <View style={styles.budgetCard}>
          <View style={styles.budgetHeadRow}>
            <Text style={styles.budgetTitle}>Monthly spend</Text>
            <Text style={styles.budgetScope}>{policy.scope === "workspace" ? "Workspace" : "Personal"}</Text>
          </View>
          <Text style={styles.budgetAmount}>
            {formatUsdMicros(policy.period_spend_micros)}
            {policy.monthly_budget_micros > 0 ? (
              <Text style={styles.budgetLimit}> {" / "}{formatUsdMicros(policy.monthly_budget_micros)}</Text>
            ) : (
              <Text style={styles.budgetLimit}>  ·  no cap set</Text>
            )}
          </Text>
          {ratio !== null ? (
            <View style={styles.track}>
              <View
                style={[
                  styles.fill,
                  { width: `${Math.round(ratio * 100)}%` },
                  ratio >= 1 && styles.fillOver,
                ]}
              />
            </View>
          ) : null}
        </View>
      ) : null}

      <View style={styles.grid}>
        {QUICK_ACTIONS.filter((action) => isRouteAvailable(action.route)).map((action) => (
          <Pressable
            key={action.key}
            style={styles.gridItem}
            onPress={() => router.push(action.route as never)}
            accessibilityRole="button"
            accessibilityLabel={action.label}
          >
            <Text style={styles.gridLabel}>{action.label}</Text>
            <Text style={styles.gridHint} numberOfLines={1}>{action.hint}</Text>
          </Pressable>
        ))}
      </View>

      <View style={styles.sectionHead}>
        <Text style={styles.sectionTitle}>Recent activity</Text>
        <Pressable onPress={() => router.push("/wallet/history")} accessibilityRole="button">
          <Text style={styles.link}>View all</Text>
        </Pressable>
      </View>
      <ActivityLedger rows={recent} emptyLabel="No wallet activity yet." />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  center: { alignItems: "center", justifyContent: "center" },
  content: { padding: 20, paddingBottom: 48 },
  error: { color: colors.error, fontSize: 14, marginBottom: 16 },
  budgetCard: {
    marginTop: 16,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 14,
    padding: 16,
  },
  budgetHeadRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  budgetTitle: { color: colors.textSecondary, fontSize: 13 },
  budgetScope: { color: colors.textSecondary, fontSize: 12, textTransform: "uppercase" },
  budgetAmount: { color: colors.textPrimary, fontSize: 22, fontWeight: "700", marginTop: 6 },
  budgetLimit: { color: colors.textSecondary, fontSize: 15, fontWeight: "500" },
  track: {
    marginTop: 12,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.cardAlt,
    overflow: "hidden",
  },
  fill: { height: 8, borderRadius: 4, backgroundColor: colors.primary },
  fillOver: { backgroundColor: colors.error },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 12, marginTop: 20 },
  gridItem: {
    flexGrow: 1,
    flexBasis: "45%",
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 14,
    padding: 16,
  },
  gridLabel: { color: colors.textPrimary, fontSize: 15, fontWeight: "600" },
  gridHint: { color: colors.textSecondary, fontSize: 12, marginTop: 4 },
  sectionHead: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: 28,
    marginBottom: 8,
  },
  sectionTitle: { color: colors.textPrimary, fontSize: 16, fontWeight: "600" },
  link: { color: colors.primary, fontSize: 14, fontWeight: "600" },
});
