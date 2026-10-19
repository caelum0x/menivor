/**
 * Route: /wallet/history — full wallet transaction ledger.
 *
 * Deepens the dashboard's recent-activity preview into a full, filterable
 * history. Wired to GET /wallet/activity → getWalletActivity(limit). The list
 * supports pull-to-refresh, entry-type filter chips (applied client-side over
 * the fetched window) and "Load more" which raises the server `limit`. Each row
 * shows the signed delta, the running balance after it and the source reason.
 * Money is server-authoritative and only formatted here.
 */

import { useCallback, useMemo, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { useFocusEffect } from "expo-router";

import { colors } from "@/components/me/theme";
import { useSession } from "@/src/shared/auth";
import { ApiError } from "@/src/shared/api";
import {
  formatUsdMicros,
  getWalletActivity,
  type WalletActivityEntry,
} from "@/lib/marketplace";
import { formatDate, formatMicrosSigned } from "@/components/wallet/format";

const PAGE_SIZE = 50;

const ENTRY_LABEL: Record<string, string> = {
  grant: "Credit added",
  reserve: "Reserved",
  settle: "Job charge",
  release: "Released",
  refund: "Refund",
  adjustment: "Adjustment",
};

interface FilterOption {
  key: string;
  label: string;
}

const FILTERS: readonly FilterOption[] = [
  { key: "all", label: "All" },
  { key: "grant", label: "Credits" },
  { key: "settle", label: "Charges" },
  { key: "refund", label: "Refunds" },
  { key: "reserve", label: "Reserved" },
  { key: "release", label: "Released" },
  { key: "adjustment", label: "Adjustments" },
];

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return fallback;
}

function rowKey(row: WalletActivityEntry, index: number): string {
  return row.id !== null ? `entry-${row.id}` : `row-${index}`;
}

export default function WalletHistoryScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const [rows, setRows] = useState<readonly WalletActivityEntry[]>([]);
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [filter, setFilter] = useState<string>("all");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [reachedEnd, setReachedEnd] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (nextLimit: number) => {
      setError(null);
      try {
        const activity = await getWalletActivity({ token }, nextLimit);
        setRows(activity);
        // If the server returned fewer than requested, there is nothing further.
        setReachedEnd(activity.length < nextLimit);
      } catch (err) {
        setError(errorMessage(err, "Failed to load your transactions."));
      }
    },
    [token],
  );

  useFocusEffect(
    useCallback(() => {
      let active = true;
      setLoading(true);
      load(PAGE_SIZE).finally(() => {
        if (active) setLoading(false);
      });
      return () => {
        active = false;
      };
    }, [load]),
  );

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    setLimit(PAGE_SIZE);
    await load(PAGE_SIZE);
    setRefreshing(false);
  }, [load]);

  const onLoadMore = useCallback(async () => {
    if (loadingMore || reachedEnd) return;
    const next = limit + PAGE_SIZE;
    setLoadingMore(true);
    setLimit(next);
    await load(next);
    setLoadingMore(false);
  }, [limit, load, loadingMore, reachedEnd]);

  const visible = useMemo(() => {
    if (filter === "all") return rows;
    return rows.filter((row) => row.entry_type === filter);
  }, [rows, filter]);

  const renderItem = useCallback(
    ({ item }: { item: WalletActivityEntry }) => {
      const positive = item.available_delta > 0;
      return (
        <View style={styles.row}>
          <View style={styles.left}>
            <Text style={styles.rowTitle}>
              {ENTRY_LABEL[item.entry_type] ?? item.entry_type}
            </Text>
            <Text style={styles.rowSub} numberOfLines={1}>
              {item.reason}
              {item.job_id ? ` · job ${item.job_id.slice(0, 8)}` : ""}
            </Text>
            {item.created_at ? (
              <Text style={styles.rowDate}>{formatDate(item.created_at)}</Text>
            ) : null}
          </View>
          <View style={styles.right}>
            <Text style={[styles.amount, positive && styles.positive]}>
              {formatMicrosSigned(item.available_delta)}
            </Text>
            <Text style={styles.bal}>bal {item.available_after_usd}</Text>
          </View>
        </View>
      );
    },
    [],
  );

  if (loading && rows.length === 0) {
    return (
      <View style={[styles.container, styles.center]}>
        <ActivityIndicator color={colors.primary} size="large" />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <View style={styles.filterBar}>
        <FlatList
          horizontal
          showsHorizontalScrollIndicator={false}
          data={FILTERS}
          keyExtractor={(f) => f.key}
          contentContainerStyle={styles.filterRow}
          renderItem={({ item }) => {
            const active = filter === item.key;
            return (
              <Pressable
                onPress={() => setFilter(item.key)}
                accessibilityRole="button"
                accessibilityState={{ selected: active }}
                style={[styles.chip, active && styles.chipActive]}
              >
                <Text style={[styles.chipText, active && styles.chipTextActive]}>{item.label}</Text>
              </Pressable>
            );
          }}
        />
      </View>

      {error ? <Text style={styles.error}>{error}</Text> : null}

      <FlatList
        data={visible}
        keyExtractor={rowKey}
        renderItem={renderItem}
        contentContainerStyle={visible.length === 0 ? styles.emptyWrap : styles.listContent}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />
        }
        onEndReachedThreshold={0.4}
        onEndReached={() => void onLoadMore()}
        ListEmptyComponent={
          <Text style={styles.empty}>
            {filter === "all"
              ? "No wallet activity yet."
              : "No transactions match this filter."}
          </Text>
        }
        ListFooterComponent={
          loadingMore ? (
            <ActivityIndicator color={colors.primary} style={styles.footerSpinner} />
          ) : reachedEnd && visible.length > 0 ? (
            <Text style={styles.footerEnd}>End of history</Text>
          ) : null
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  center: { alignItems: "center", justifyContent: "center" },
  filterBar: { borderBottomWidth: 1, borderBottomColor: colors.border },
  filterRow: { gap: 8, paddingHorizontal: 16, paddingVertical: 12 },
  chip: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 7,
  },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { color: colors.textPrimary, fontSize: 13, fontWeight: "600" },
  chipTextActive: { color: colors.bg },
  error: { color: colors.error, fontSize: 14, paddingHorizontal: 20, paddingTop: 12 },
  listContent: { paddingHorizontal: 20, paddingBottom: 40 },
  emptyWrap: { flexGrow: 1, justifyContent: "center", paddingHorizontal: 20 },
  empty: { color: colors.textSecondary, fontSize: 14, textAlign: "center" },
  row: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    gap: 12,
  },
  left: { flex: 1 },
  rowTitle: { color: colors.textPrimary, fontSize: 15, fontWeight: "500" },
  rowSub: { color: colors.textSecondary, fontSize: 12, marginTop: 2 },
  rowDate: { color: colors.muted, fontSize: 11, marginTop: 3 },
  right: { alignItems: "flex-end" },
  amount: { color: colors.textPrimary, fontSize: 15, fontWeight: "600" },
  positive: { color: colors.success },
  bal: { color: colors.textSecondary, fontSize: 11, marginTop: 2 },
  footerSpinner: { marginVertical: 20 },
  footerEnd: { color: colors.muted, fontSize: 12, textAlign: "center", marginVertical: 20 },
});
