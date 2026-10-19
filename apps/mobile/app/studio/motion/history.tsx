/**
 * Studio · Motion Compile History.
 *
 * Nav manifest: { route: "/studio/motion/history", title: "Compile History" }
 *
 * The caller's recent compiled/dispatched camera moves (GET /motion/history),
 * newest first — every time a preset is compiled on the detail screen a row is
 * recorded here (best-effort, server-side). List with pull-to-refresh; each row
 * shows the preset, its resolved render class, the intensity it was compiled
 * at, the provider key (for model/hybrid) and any output reference. Tap a row to
 * jump back to that preset's detail. History needs the backend DB, so a 503 is
 * surfaced as a friendly "history unavailable" state rather than a hard error.
 */

import { useCallback, useState } from "react";
import {
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { useRouter } from "expo-router";

import {
  getMotionHistory,
  type MotionHistoryEntry,
} from "@/lib/api/motion";
import { useSession } from "@/src/shared/auth";

import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import { StudioScreen } from "@/components/studio/StudioScreen";

const HISTORY_LIMIT = 50;

export default function StudioMotionHistoryScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();

  const [entries, setEntries] = useState<MotionHistoryEntry[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(
    async (mode: "initial" | "refresh") => {
      if (mode === "initial") setStatus("loading");
      else setRefreshing(true);
      try {
        const data = await getMotionHistory({ limit: HISTORY_LIMIT }, { token });
        setEntries(data);
        setStatus("ready");
        setError("");
      } catch (err) {
        setError(
          describeError(
            err,
            "Compile history is unavailable right now. Try again shortly.",
          ),
        );
        if (mode === "initial") setStatus("error");
      } finally {
        if (mode === "refresh") setRefreshing(false);
      }
    },
    [token],
  );

  const keyExtractor = useCallback((e: MotionHistoryEntry) => e.id, []);

  const renderItem = useCallback(
    ({ item }: { item: MotionHistoryEntry }) => (
      <Pressable
        style={styles.card}
        onPress={() =>
          router.push({
            pathname: "/studio/motion/[id]",
            params: { id: item.preset_id },
          })
        }
        accessibilityRole="button"
        accessibilityLabel={`Motion ${item.preset_id}`}
      >
        <View style={styles.head}>
          <Text style={styles.preset} numberOfLines={1}>
            {item.preset_id}
          </Text>
          <View style={styles.classBadge}>
            <Text style={styles.classText}>{item.motion_class}</Text>
          </View>
        </View>
        <View style={styles.metaRow}>
          <Text style={styles.meta}>Intensity {item.intensity}</Text>
          {item.provider_key ? (
            <Text style={styles.meta}>· {item.provider_key}</Text>
          ) : null}
        </View>
        <Text style={styles.output} numberOfLines={1}>
          {item.output_ref ? item.output_ref : "Plan compiled (no render output)"}
        </Text>
      </Pressable>
    ),
    [router],
  );

  const header = (
    <Text style={styles.intro}>
      Every camera move you compile is recorded here so a reel's look is
      reproducible. Tap a row to reopen that preset.
    </Text>
  );

  return (
    <StudioScreen
      status={status}
      error={error}
      onRetry={() => void load("initial")}
      loadingLabel="Loading compile history…"
    >
      <FlatList
        data={entries}
        keyExtractor={keyExtractor}
        renderItem={renderItem}
        ListHeaderComponent={header}
        contentContainerStyle={styles.list}
        ItemSeparatorComponent={Separator}
        ListEmptyComponent={
          <Text style={styles.empty}>
            No compiled moves yet. Open a motion preset and compile it against a
            reel — it will show up here.
          </Text>
        }
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => void load("refresh")}
            tintColor={colors.accent}
          />
        }
      />
    </StudioScreen>
  );
}

function Separator() {
  return <View style={styles.sep} />;
}

const styles = StyleSheet.create({
  list: { padding: 16, paddingBottom: 48 },
  intro: {
    color: colors.textSecondary,
    fontSize: 14,
    lineHeight: 20,
    marginBottom: 12,
  },
  sep: { height: 10 },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 6,
  },
  head: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
  },
  preset: { flex: 1, color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  classBadge: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 3,
  },
  classText: { color: colors.textSecondary, fontSize: 11, fontWeight: "700" },
  metaRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  meta: { color: colors.muted, fontSize: 12 },
  output: { color: colors.textSecondary, fontSize: 12, fontFamily: "monospace" },
  empty: {
    color: colors.muted,
    fontSize: 14,
    lineHeight: 20,
    paddingVertical: 24,
    textAlign: "center",
  },
});
