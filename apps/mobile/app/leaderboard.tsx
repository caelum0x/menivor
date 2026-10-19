/**
 * Creator Leaderboard screen.
 *
 * A PUBLIC ranking of creators by a documented, deterministic metric
 * (reputation | followers | clones | rating | published | win_score). The list is
 * fetched through the shared api client; the leaderboard endpoint is public, but
 * the session token is forwarded when present (harmless). Every row exposes ONLY
 * safe public fields — never credits, email, cost/revenue or any private datum.
 *
 * A single async resource owns the loading / ready / error lifecycle keyed on the
 * selected metric, so switching metric re-fetches. Tapping a row deep-links to the
 * creator's public profile. Paging is bounded server-side (limit clamped 1..100).
 */

import { useCallback, useState } from "react";
import { FlatList, RefreshControl, StyleSheet, Text, View } from "react-native";

import { useRouter } from "expo-router";

import { getLeaderboard } from "@/lib/api";
import { useSession } from "@/src/shared/auth";
import {
  DEFAULT_LEADERBOARD_LIMIT,
  type LeaderboardEntry,
  type LeaderboardMetric,
} from "@/lib/types";

import { SectionState } from "@/components/me/Section";
import { colors } from "@/components/me/theme";
import { useResource } from "@/components/me/use-resource";
import { LeaderboardMetricPicker } from "@/components/creators/LeaderboardMetricPicker";
import { LeaderboardRow } from "@/components/creators/LeaderboardRow";

export default function LeaderboardScreen() {
  const { apiKey } = useSession();
  const router = useRouter();
  const token = apiKey ?? undefined;

  const [metric, setMetric] = useState<LeaderboardMetric>("reputation");

  const fetcher = useCallback(
    () => getLeaderboard({ token, metric, limit: DEFAULT_LEADERBOARD_LIMIT }),
    [token, metric],
  );
  const board = useResource<LeaderboardEntry[]>(fetcher);

  const onOpenCreator = useCallback(
    (userId: string) => {
      if (userId) router.push(`/creator/${userId}`);
    },
    [router],
  );

  const data = board.data ?? [];
  const isReady = board.status === "ready";

  return (
    <FlatList
      style={styles.container}
      contentContainerStyle={styles.content}
      data={data}
      keyExtractor={(item) => item.user_id}
      refreshControl={
        <RefreshControl
          refreshing={false}
          onRefresh={board.reload}
          tintColor={colors.accent}
        />
      }
      ListHeaderComponent={
        <View style={styles.header}>
          <Text style={styles.intro}>
            The top creators, ranked by a transparent reputation score. Switch the
            metric to rank by followers, clones, rating, published templates or
            downstream win-score. Tap a creator to view their profile.
          </Text>
          <LeaderboardMetricPicker metric={metric} onChange={setMetric} />
        </View>
      }
      renderItem={({ item }) => (
        <LeaderboardRow entry={item} metric={metric} onPress={onOpenCreator} />
      )}
      ItemSeparatorComponent={() => <View style={styles.separator} />}
      ListEmptyComponent={
        <SectionState
          status={board.status}
          error={board.error}
          onRetry={board.reload}
          loadingLabel="Loading leaderboard…"
        >
          {isReady ? (
            <Text style={styles.muted}>
              No ranked creators yet. Publish templates and grow your following to
              climb the board.
            </Text>
          ) : null}
        </SectionState>
      }
    />
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20, paddingTop: 24, gap: 12 },
  header: { gap: 16, marginBottom: 4 },
  intro: { color: colors.textSecondary, fontSize: 14, lineHeight: 20 },
  separator: { height: 10 },
  muted: { color: colors.muted, fontSize: 13 },
});
