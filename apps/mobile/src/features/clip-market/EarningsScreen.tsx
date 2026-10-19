/**
 * EarningsScreen — a clipper/brand's money view for ClipMarket. Paid-out clips
 * land as wallet credits, so this reads the wallet plus the caller's campaigns:
 * - GET /wallet          → {@link getWalletBalance}
 * - GET /wallet/activity → {@link getWalletActivity}
 * - GET /clipmarket/campaigns → {@link listCampaigns} (for aggregate spend)
 *
 * All three are REAL reads through the shared client (token → `x-api-key`).
 * Money is rendered from server micros / `*_usd` strings via `formatUsdMicros`
 * and `summarizeSpend`; nothing is computed beyond a pure reduction. Read-only:
 * no wallet mutation happens here. Pull-to-refresh reloads everything.
 *
 * NOTE: no route lists a clipper's own submissions, so lifetime earned-per-clip
 * is out of scope until a backend route exists.
 */

import * as React from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { colors } from "@/components/me/theme";
import { ApiError, isAbortError, makeAbortError } from "@/src/shared/api";
import { useSession } from "@/src/shared/auth";
import { listCampaigns, type Campaign } from "@/lib/clipmarket";
import {
  getWalletActivity,
  getWalletBalance,
  type WalletActivityEntry,
  type WalletBalance,
} from "@/lib/earnings";

import { ActivityRow } from "./components/ActivityRow";
import { EarningsSummary } from "./components/EarningsSummary";
import { summarizeSpend } from "./logic";

const ACTIVITY_LIMIT = 50;

type Phase = "loading" | "ready" | "error";

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return fallback;
}

export function EarningsScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const [balance, setBalance] = React.useState<WalletBalance | null>(null);
  const [activity, setActivity] = React.useState<WalletActivityEntry[]>([]);
  const [campaigns, setCampaigns] = React.useState<Campaign[]>([]);
  const [phase, setPhase] = React.useState<Phase>("loading");
  const [error, setError] = React.useState<string | null>(null);
  const [refreshing, setRefreshing] = React.useState(false);

  const inFlight = React.useRef<AbortController | null>(null);

  const load = React.useCallback(
    async (mode: "initial" | "refresh") => {
      inFlight.current?.abort(makeAbortError());
      const controller = new AbortController();
      inFlight.current = controller;
      const options = { token, signal: controller.signal };

      if (mode === "refresh") setRefreshing(true);
      else setPhase("loading");
      setError(null);

      try {
        const [walletBalance, walletActivity, campaignList] = await Promise.all([
          getWalletBalance(options),
          getWalletActivity(ACTIVITY_LIMIT, 0, options),
          listCampaigns(options),
        ]);
        if (controller.signal.aborted) return;
        setBalance(walletBalance);
        setActivity(walletActivity);
        setCampaigns(campaignList.campaigns);
        setPhase("ready");
      } catch (err) {
        if (isAbortError(err) || controller.signal.aborted) return;
        setError(errorMessage(err, "Failed to load your earnings."));
        setPhase("error");
      } finally {
        if (inFlight.current === controller) inFlight.current = null;
        if (mode === "refresh") setRefreshing(false);
      }
    },
    [token],
  );

  React.useEffect(() => {
    void load("initial");
    return () => inFlight.current?.abort(makeAbortError());
  }, [load]);

  const spend = React.useMemo(() => summarizeSpend(campaigns), [campaigns]);

  const renderItem = React.useCallback(
    ({ item }: { item: WalletActivityEntry }) => <ActivityRow entry={item} />,
    [],
  );

  const header = (
    <View style={styles.header}>
      <EarningsSummary balance={balance} spend={spend} />
      <Text style={styles.sectionTitle}>Recent activity</Text>
    </View>
  );

  const empty = (() => {
    if (phase === "loading" && !refreshing) {
      return (
        <View style={styles.state}>
          <ActivityIndicator color={colors.primary} />
          <Text style={styles.stateText}>Loading your earnings…</Text>
        </View>
      );
    }
    if (phase === "error") {
      return (
        <View style={styles.state}>
          <Text style={styles.errorText}>{error}</Text>
          <Pressable
            style={styles.retry}
            accessibilityRole="button"
            onPress={() => void load("initial")}
            testID="earnings-retry"
          >
            <Text style={styles.retryText}>Retry</Text>
          </Pressable>
        </View>
      );
    }
    return (
      <View style={styles.state}>
        <Text style={styles.stateText}>
          No wallet activity yet. Paid-out clips and top-ups will show here.
        </Text>
      </View>
    );
  })();

  return (
    <FlatList
      style={styles.container}
      contentContainerStyle={styles.content}
      data={activity}
      keyExtractor={(row, index) => (row.id != null ? String(row.id) : `row-${index}`)}
      renderItem={renderItem}
      ListHeaderComponent={header}
      ListEmptyComponent={empty}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={() => void load("refresh")}
          tintColor={colors.primary}
        />
      }
      testID="earnings-list"
    />
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16, paddingBottom: 40 },
  header: { gap: 14, marginBottom: 8 },
  sectionTitle: {
    color: colors.textPrimary,
    fontSize: 18,
    fontWeight: "800",
    marginTop: 4,
  },
  state: { alignItems: "center", gap: 12, paddingVertical: 32 },
  stateText: {
    color: colors.textSecondary,
    fontSize: 14,
    textAlign: "center",
    lineHeight: 20,
  },
  errorText: { color: colors.error, fontSize: 14, textAlign: "center" },
  retry: {
    borderColor: colors.primary,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 20,
    paddingVertical: 10,
  },
  retryText: { color: colors.primary, fontSize: 14, fontWeight: "700" },
});
