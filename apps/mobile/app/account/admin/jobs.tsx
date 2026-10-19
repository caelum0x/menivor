/**
 * Platform-admin: cross-tenant job history (GET /admin/jobs), newest first, with
 * pull-to-refresh and append-style pagination. Read-only — a live state badge +
 * progress bar per job. Staff-gated server-side.
 *
 * NAV MANIFEST:
 *   - { route: "/account/admin/jobs", title: "All Jobs" }
 */

import * as React from "react";
import {
  FlatList,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { Stack } from "expo-router";

import { colors } from "@/components/me/theme";
import { adminListJobs } from "@/lib/api";
import {
  AdminListState,
  Badge,
  Card,
  KeyValue,
  LoadMoreFooter,
  adminStyles,
  formatDateTime,
  jobStateLabel,
} from "@/components/admin/ui";
import { useAdminList } from "@/components/admin/use-admin-list";
import { DEFAULT_ADMIN_LIMIT, JobState } from "@/lib/types";
import type { AdminJob } from "@/lib/types";
import { useSession } from "@/src/shared/auth";

function toneForState(state: number | null): "neutral" | "success" | "danger" {
  if (state === JobState.Complete) return "success";
  if (state === JobState.Failed) return "danger";
  return "neutral";
}

export default function AdminJobsScreen(): React.ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const fetcher = React.useCallback(
    (
      window: { limit: number; offset: number },
      transport: { token?: string; signal: AbortSignal },
    ) => adminListJobs(window, transport),
    [],
  );

  const list = useAdminList<AdminJob>(fetcher, token, DEFAULT_ADMIN_LIMIT);

  const renderItem = React.useCallback(
    ({ item }: { item: AdminJob }): React.ReactElement => {
      const progress = Math.max(0, Math.min(100, item.progress ?? 0));
      return (
        <Card>
          <View style={styles.rowBetween}>
            <Text style={styles.kind} numberOfLines={1}>
              {item.kind || "job"}
            </Text>
            <Badge
              label={jobStateLabel(item.state, item.progress)}
              tone={toneForState(item.state)}
            />
          </View>
          <KeyValue label="Job id" value={item.id} />
          <KeyValue label="User id" value={item.user_id} />
          <KeyValue label="Created" value={formatDateTime(item.created_at)} />
          <View style={styles.progressTrack}>
            <View style={[styles.progressFill, { width: `${progress}%` }]} />
          </View>
          <Text style={styles.progressLabel}>{progress}%</Text>
        </Card>
      );
    },
    [],
  );

  return (
    <View style={adminStyles.container}>
      <Stack.Screen options={{ title: "All Jobs" }} />
      <FlatList
        data={list.items as AdminJob[]}
        keyExtractor={(item) => item.id}
        renderItem={renderItem}
        contentContainerStyle={adminStyles.content}
        refreshControl={
          <RefreshControl
            refreshing={list.status === "refreshing"}
            onRefresh={list.refresh}
            tintColor={colors.accent}
          />
        }
        onEndReachedThreshold={0.4}
        onEndReached={list.loadMore}
        ListHeaderComponent={
          <Text style={adminStyles.intro}>
            Every job across every tenant, newest first.
          </Text>
        }
        ListEmptyComponent={
          <AdminListState
            loading={list.initialLoading}
            error={list.error}
            empty={list.status === "ready"}
            emptyTitle="No jobs"
            emptyHint="No jobs were returned for this window."
            onRetry={list.refresh}
          />
        }
        ListFooterComponent={
          <LoadMoreFooter
            hasMore={list.hasMore}
            loading={list.status === "loadingMore"}
            count={list.items.length}
            onLoadMore={list.loadMore}
          />
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  rowBetween: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  kind: {
    color: colors.textPrimary,
    fontSize: 16,
    fontWeight: "700",
    flexShrink: 1,
    textTransform: "capitalize",
  },
  progressTrack: {
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.cardAlt,
    overflow: "hidden",
    marginTop: 4,
  },
  progressFill: { height: 6, borderRadius: 3, backgroundColor: colors.accent },
  progressLabel: { color: colors.muted, fontSize: 11, textAlign: "right" },
});
