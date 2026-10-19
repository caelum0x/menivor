/**
 * Clipfarm Console — the Wave-2 group console for the unattended channel runner.
 *
 * One channel at a time: read its REAL run history (`GET /series/channels/{id}/
 * runs`) and pacing (`GET /series/channels/{id}/pending`), trigger a render pass
 * (`POST /series/channels/{id}/run`) and pace pending clips onto the publish
 * calendar (`POST /series/channels/{id}/schedule`). Every number comes from the
 * runner/repositories over HTTP — there is NO client-side mock data. Both POST
 * paths send a minted `Idempotency-Key` (required by the backend).
 */

import * as React from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { useLocalSearchParams } from "expo-router";

import { colors } from "@/components/me/theme";
import { isAbortError, makeAbortError } from "@/src/shared/api";
import { useSession } from "@/src/shared/auth";
import {
  getChannelPacing,
  listChannelRuns,
  triggerChannelRun,
  triggerChannelSchedule,
  type ChannelPacing,
  type ChannelRunView,
  type RunChannelInput,
} from "@/lib/series";

import { PacingPanel } from "./components/PacingPanel";
import { RunHistoryCard } from "./components/RunHistoryCard";
import { TriggerPanel } from "./components/TriggerPanel";
import {
  formatRunSummary,
  formatScheduleSummary,
  newIdempotencyKey,
} from "./logic";

const RUN_LIMIT = 50;

type Phase = "idle" | "loading" | "ready" | "error";

function paramChannelId(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return value[0] ?? "";
  return value ?? "";
}

export function ClipfarmConsoleScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const params = useLocalSearchParams<{ channel_id?: string }>();

  const [channelId, setChannelId] = React.useState<string>(() =>
    paramChannelId(params.channel_id).trim(),
  );
  const [activeChannel, setActiveChannel] = React.useState<string>(() =>
    paramChannelId(params.channel_id).trim(),
  );

  const [runs, setRuns] = React.useState<ChannelRunView[]>([]);
  const [pacing, setPacing] = React.useState<ChannelPacing | null>(null);
  const [phase, setPhase] = React.useState<Phase>(activeChannel ? "loading" : "idle");
  const [error, setError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [refreshing, setRefreshing] = React.useState(false);
  const [triggering, setTriggering] = React.useState(false);
  const [scheduling, setScheduling] = React.useState(false);

  const inFlight = React.useRef<AbortController | null>(null);

  const load = React.useCallback(
    async (channel: string, mode: "initial" | "refresh") => {
      if (!channel) {
        setPhase("idle");
        return;
      }
      inFlight.current?.abort(makeAbortError());
      const controller = new AbortController();
      inFlight.current = controller;

      if (mode === "refresh") setRefreshing(true);
      else setPhase("loading");
      setError(null);

      try {
        const [runsRes, pacingRes] = await Promise.all([
          listChannelRuns(channel, RUN_LIMIT, {
            token,
            signal: controller.signal,
          }),
          getChannelPacing(channel, { token, signal: controller.signal }),
        ]);
        if (controller.signal.aborted) return;
        setRuns(runsRes.runs);
        setPacing(pacingRes);
        setPhase("ready");
      } catch (err) {
        if (isAbortError(err) || controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : "Failed to load channel.");
        setPhase("error");
      } finally {
        if (inFlight.current === controller) inFlight.current = null;
        if (mode === "refresh") setRefreshing(false);
      }
    },
    [token],
  );

  React.useEffect(() => {
    if (activeChannel) void load(activeChannel, "initial");
    return () => inFlight.current?.abort(makeAbortError());
  }, [activeChannel, load]);

  const openChannel = React.useCallback(() => {
    const next = channelId.trim();
    setNotice(null);
    setError(null);
    setActiveChannel(next);
    if (!next) {
      setRuns([]);
      setPacing(null);
      setPhase("idle");
    }
  }, [channelId]);

  const onTriggerRun = React.useCallback(
    async (input: RunChannelInput) => {
      if (!activeChannel || triggering) return;
      setTriggering(true);
      setError(null);
      setNotice(null);
      try {
        const res = await triggerChannelRun(activeChannel, input, {
          token,
          idempotencyKey: newIdempotencyKey("run"),
        });
        setNotice(`Run ${res.run_id}: ${formatRunSummary(res.summary)}`);
        await load(activeChannel, "refresh");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to trigger run.");
      } finally {
        setTriggering(false);
      }
    },
    [activeChannel, load, token, triggering],
  );

  const onSchedule = React.useCallback(async () => {
    if (!activeChannel || scheduling) return;
    setScheduling(true);
    setError(null);
    setNotice(null);
    try {
      const platforms = Object.keys(pacing?.rendered_today ?? {});
      const res = await triggerChannelSchedule(
        activeChannel,
        { platforms: platforms.filter((p) => p.length > 0) },
        { token, idempotencyKey: newIdempotencyKey("schedule") },
      );
      setNotice(formatScheduleSummary(res.summary));
      await load(activeChannel, "refresh");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to schedule pending clips.",
      );
    } finally {
      setScheduling(false);
    }
  }, [activeChannel, load, pacing, scheduling, token]);

  const header = (
    <View style={styles.header}>
      <Text style={styles.title}>Clipfarm console</Text>
      <Text style={styles.intro}>
        Point the unattended runner at a channel: read its runs + pacing, trigger
        a render pass, and pace completed clips onto the publish calendar.
      </Text>

      <View style={styles.channelRow}>
        <TextInput
          style={styles.channelInput}
          autoCapitalize="none"
          autoCorrect={false}
          placeholder="channel_id"
          placeholderTextColor={colors.muted}
          value={channelId}
          onChangeText={setChannelId}
          onSubmitEditing={openChannel}
          testID="channel-input"
        />
        <Pressable
          style={styles.openBtn}
          onPress={openChannel}
          accessibilityRole="button"
          testID="open-channel-button"
        >
          <Text style={styles.openBtnText}>Open</Text>
        </Pressable>
      </View>

      {notice ? (
        <Text style={styles.notice} testID="console-notice">
          {notice}
        </Text>
      ) : null}
      {error ? (
        <Text style={styles.error} testID="console-error">
          {error}
        </Text>
      ) : null}

      {activeChannel ? (
        <>
          <TriggerPanel submitting={triggering} onSubmit={onTriggerRun} />
          <View style={styles.divider} />
          <Text style={styles.sectionTitle}>Pacing</Text>
          <PacingPanel
            pacing={pacing}
            onSchedule={onSchedule}
            scheduling={scheduling}
          />
          <View style={styles.divider} />
          <Text style={styles.sectionTitle}>Run history</Text>
        </>
      ) : null}
    </View>
  );

  const empty = (() => {
    if (!activeChannel) {
      return (
        <View style={styles.state}>
          <Text style={styles.stateText}>
            Enter a channel_id above and tap Open to load its runner console.
          </Text>
        </View>
      );
    }
    if (phase === "loading" && !refreshing) {
      return (
        <View style={styles.state}>
          <ActivityIndicator color={colors.primary} />
          <Text style={styles.stateText}>Loading channel…</Text>
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
            onPress={() => void load(activeChannel, "initial")}
            testID="console-retry"
          >
            <Text style={styles.retryText}>Retry</Text>
          </Pressable>
        </View>
      );
    }
    return (
      <View style={styles.state}>
        <Text style={styles.stateText}>
          No runs yet for this channel. Trigger a render pass above to start.
        </Text>
      </View>
    );
  })();

  return (
    <FlatList
      style={styles.container}
      contentContainerStyle={styles.content}
      data={activeChannel ? runs : []}
      keyExtractor={(run) => run.id}
      renderItem={({ item }) => <RunHistoryCard run={item} />}
      ListHeaderComponent={header}
      ListEmptyComponent={empty}
      ItemSeparatorComponent={() => <View style={styles.gap} />}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={() =>
            activeChannel ? void load(activeChannel, "refresh") : undefined
          }
          tintColor={colors.primary}
        />
      }
      testID="clipfarm-run-list"
    />
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16, paddingBottom: 40 },
  header: { gap: 12, marginBottom: 12 },
  title: { color: colors.textPrimary, fontSize: 22, fontWeight: "800" },
  intro: { color: colors.textSecondary, fontSize: 14, lineHeight: 20 },
  channelRow: { flexDirection: "row", gap: 10 },
  channelInput: {
    flex: 1,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: colors.textPrimary,
    backgroundColor: colors.card,
    fontSize: 15,
  },
  openBtn: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingHorizontal: 20,
    justifyContent: "center",
  },
  openBtnText: { color: "#fff", fontSize: 15, fontWeight: "700" },
  divider: { height: 1, backgroundColor: colors.border, marginVertical: 4 },
  sectionTitle: { color: colors.textPrimary, fontSize: 18, fontWeight: "800" },
  notice: { color: colors.success, fontSize: 13 },
  error: { color: colors.error, fontSize: 13 },
  gap: { height: 12 },
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
