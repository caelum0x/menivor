/**
 * Route: /inbox — the social inbox on mobile. Comments and messages on the
 * posts Menivor published, filtered by status, platform and kind, with a
 * "Sync now" pull. Tap a thread to read it and reply (/inbox/[id]).
 *
 * Backed by GET /social-inbox, POST /social-inbox/sync and
 * GET /social-inbox/threads. Platform coverage is capability-driven: the
 * header lists which connected platforms can actually be read.
 */

import { useCallback, useMemo, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { Stack, useFocusEffect, useRouter } from "expo-router";

import { ApiError } from "@/src/shared/api";
import { useSession } from "@/src/shared/auth";
import { colors, radius, spacing, typeScale } from "@/src/shared/theme";
import { Button, Chip, EmptyState, ErrorState } from "@/components/ui";
import { Icon } from "@/components/ui/Icon";
import {
  DEFAULT_FILTERS,
  INBOX_PAGE_SIZE,
  STATUS_LABEL,
  getInboxOverview,
  listThreads,
  mergeThreads,
  readableApiMessage,
  readablePlatforms,
  relativeTime,
  syncInbox,
  type InboxOverview,
  type InboxThread,
  type ThreadFilters,
  type ThreadStatus,
} from "@/lib/social-inbox";

const STATUS_TABS: readonly (ThreadStatus | "all")[] = ["needs_reply", "replied", "done", "all"];

function describe(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 429) return "Synced a moment ago. Try again in a minute.";
    if (err.status === 503) return "The inbox is unavailable right now.";
    return readableApiMessage(err.message, fallback);
  }
  return err instanceof Error ? err.message : fallback;
}

export default function InboxScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();

  const [filters, setFilters] = useState<ThreadFilters>(DEFAULT_FILTERS);
  const [overview, setOverview] = useState<InboxOverview | null>(null);
  const [threads, setThreads] = useState<InboxThread[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(
    async (next: ThreadFilters) => {
      setError(null);
      try {
        const [ov, page] = await Promise.all([
          getInboxOverview({ token }),
          listThreads(next, 0, { token }),
        ]);
        setOverview(ov);
        setThreads(page.threads);
        setTotal(page.total);
      } catch (err) {
        setError(describe(err, "Could not load your inbox."));
      }
    },
    [token],
  );

  useFocusEffect(
    useCallback(() => {
      let active = true;
      setLoading(true);
      load(filters).finally(() => {
        if (active) setLoading(false);
      });
      return () => {
        active = false;
      };
    }, [load, filters]),
  );

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load(filters);
    setRefreshing(false);
  }, [load, filters]);

  const onSync = useCallback(async () => {
    setSyncing(true);
    setNotice(null);
    setError(null);
    try {
      const ov = await syncInbox({ token });
      setOverview(ov);
      const synced = ov.sync?.synced ?? 0;
      setNotice(synced > 0 ? `Pulled ${synced} new item${synced === 1 ? "" : "s"}.` : "No new comments or messages.");
      const page = await listThreads(filters, 0, { token });
      setThreads(page.threads);
      setTotal(page.total);
    } catch (err) {
      setError(describe(err, "Could not sync the inbox."));
    } finally {
      setSyncing(false);
    }
  }, [token, filters]);

  const onEndReached = useCallback(async () => {
    if (loadingMore || loading || threads.length >= total) return;
    setLoadingMore(true);
    try {
      const page = await listThreads(filters, threads.length, { token });
      setThreads((prev) => mergeThreads(prev, page.threads));
      setTotal(page.total);
    } catch (err) {
      setError(describe(err, "Could not load more threads."));
    } finally {
      setLoadingMore(false);
    }
  }, [filters, loading, loadingMore, threads.length, token, total]);

  const readable = useMemo(
    () => readablePlatforms(overview?.platforms ?? []),
    [overview],
  );
  const needsAttention = useMemo(
    () => (overview?.platforms ?? []).filter((p) => p.connected && p.needs_reconnect),
    [overview],
  );

  const header = (
    <View style={styles.header}>
      <Text style={styles.lead}>
        Comments and messages on posts Menivor published. Reply here where the platform allows it; otherwise
        open the post and reply there.
      </Text>
      <View style={styles.row}>
        <Button
          label={syncing ? "Syncing" : "Sync now"}
          variant="secondary"
          size="sm"
          loading={syncing}
          onPress={onSync}
          disabled={syncing}
        />
        {overview?.last_synced_at ? (
          <Text style={styles.faint}>Last synced {relativeTime(overview.last_synced_at)}</Text>
        ) : null}
      </View>
      {notice ? <Text style={styles.notice}>{notice}</Text> : null}
      {needsAttention.length > 0 ? (
        <Text style={styles.warn}>
          {needsAttention.map((p) => p.label).join(", ")} need reconnecting with inbox access. Reconnect from
          Connections.
        </Text>
      ) : null}

      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
        {STATUS_TABS.map((status) => {
          const count = status === "all" ? null : overview?.totals.by_status[status];
          const label = status === "all" ? "All" : STATUS_LABEL[status];
          return (
            <Chip
              key={status}
              label={typeof count === "number" ? `${label} ${count}` : label}
              active={filters.status === status}
              onPress={() => setFilters((f) => ({ ...f, status }))}
            />
          );
        })}
      </ScrollView>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
        <Chip
          label="All platforms"
          active={filters.platform === ""}
          onPress={() => setFilters((f) => ({ ...f, platform: "" }))}
        />
        {readable.map((p) => (
          <Chip
            key={p.platform}
            label={p.label}
            active={filters.platform === p.platform}
            onPress={() => setFilters((f) => ({ ...f, platform: p.platform }))}
          />
        ))}
        <Chip
          label="Comments"
          active={filters.kind === "comment"}
          onPress={() => setFilters((f) => ({ ...f, kind: f.kind === "comment" ? "" : "comment" }))}
        />
        <Chip
          label="Messages"
          active={filters.kind === "dm"}
          onPress={() => setFilters((f) => ({ ...f, kind: f.kind === "dm" ? "" : "dm" }))}
        />
      </ScrollView>
      {error ? <ErrorState message={error} onRetry={() => load(filters)} /> : null}
    </View>
  );

  return (
    <>
      <Stack.Screen options={{ title: "Inbox" }} />
      {loading && threads.length === 0 ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.accent} />
        </View>
      ) : (
        <FlatList
          style={styles.list}
          contentContainerStyle={styles.listContent}
          data={threads}
          keyExtractor={(t) => t.id}
          ListHeaderComponent={header}
          ListEmptyComponent={
            error ? null : (
              <EmptyState
                title={readable.length === 0 ? "No readable platforms yet" : "Nothing here"}
                body={
                  readable.length === 0
                    ? "Connect a platform that shares comments or messages with apps, publish a post, then sync."
                    : "No threads match these filters. Sync to pull new comments and messages."
                }
                actionLabel={readable.length === 0 ? "Open Connections" : undefined}
                onAction={readable.length === 0 ? () => router.push("/connections") : undefined}
              />
            )
          }
          renderItem={({ item }) => (
            <Pressable
              style={({ pressed }) => [styles.thread, pressed && styles.pressed]}
              onPress={() => router.push({ pathname: "/inbox/[id]", params: { id: item.id } })}
              accessibilityRole="button"
              accessibilityLabel={`${item.author_name} on ${item.platform_label}`}
            >
              <View style={styles.threadTop}>
                <Icon
                  name={item.kind === "dm" ? "mail-outline" : "chatbubble-outline"}
                  size={16}
                  color={colors.textSecondary}
                />
                <Text style={styles.author} numberOfLines={1}>
                  {item.author_name || "Someone"}
                </Text>
                <Text style={styles.faint}>
                  {item.platform_label} · {relativeTime(item.last_message_at)}
                </Text>
              </View>
              <Text style={styles.body} numberOfLines={2}>
                {item.text}
              </Text>
              <View style={styles.threadBottom}>
                {item.post_title ? (
                  <Text style={styles.faint} numberOfLines={1}>
                    On: {item.post_title}
                  </Text>
                ) : (
                  <View />
                )}
                <Text style={[styles.status, item.status === "needs_reply" && styles.statusOpen]}>
                  {STATUS_LABEL[item.status]}
                </Text>
              </View>
            </Pressable>
          )}
          onEndReachedThreshold={0.4}
          onEndReached={onEndReached}
          ListFooterComponent={
            loadingMore ? (
              <ActivityIndicator color={colors.accent} style={styles.footer} />
            ) : threads.length >= INBOX_PAGE_SIZE && threads.length < total ? (
              <Text style={[styles.faint, styles.footer]}>Scroll for more</Text>
            ) : null
          }
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />
          }
        />
      )}
    </>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.bg },
  list: { flex: 1, backgroundColor: colors.bg },
  listContent: { padding: spacing.lg, gap: spacing.sm, paddingBottom: spacing.xxl },
  header: { gap: spacing.md, marginBottom: spacing.sm },
  lead: { color: colors.textSecondary, fontSize: typeScale.caption, lineHeight: 19 },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  chips: { gap: spacing.sm, paddingRight: spacing.lg },
  notice: { color: colors.success, fontSize: typeScale.caption },
  warn: { color: colors.accent, fontSize: typeScale.caption, lineHeight: 18 },
  faint: { color: colors.textFaint, fontSize: typeScale.micro },
  thread: {
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    padding: spacing.md,
    gap: spacing.xs,
  },
  pressed: { opacity: 0.7 },
  threadTop: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  author: { color: colors.textPrimary, fontSize: typeScale.body, fontWeight: "600", flexShrink: 1 },
  body: { color: colors.textPrimary, fontSize: typeScale.caption, lineHeight: 19 },
  threadBottom: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: spacing.sm },
  status: { color: colors.textSecondary, fontSize: typeScale.micro, fontWeight: "600" },
  statusOpen: { color: colors.accent },
  footer: { marginVertical: spacing.lg, alignSelf: "center" },
});
