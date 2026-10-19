/**
 * Channels: Telegram channels and groups, Discord channels and Mastodon
 * accounts. Their APIs are free and need no platform review, so a connected
 * channel works right away. At parity with the web /calendar/channels page,
 * plus the channel publish composer and the channel post queue:
 *
 *   GET/POST/DELETE /publishing/channels*      connect, re-check, test, disconnect
 *   POST /publishing/channel-posts             post now or schedule
 *   GET  /publishing/calendar/entries          queue (filtered to channel posts)
 *
 * Credentials are encrypted server-side and never shown again. No emoji.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Alert, Linking, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { Stack } from "expo-router";

import { ActionButton } from "@/components/approvals/Button";
import { ui } from "@/components/approvals/styles";
import { ChannelComposer } from "@/components/channels/ChannelComposer";
import { ChannelRow, type ChannelAction, type RowNote } from "@/components/channels/ChannelRow";
import { ConnectChannelForm } from "@/components/channels/ConnectChannelForm";
import { LaunchStatusBanner } from "@/components/launch/LaunchStatusBanner";
import { colors } from "@/components/me/theme";
import {
  disconnectChannel,
  getChannelQueue,
  getChannels,
  testChannel,
  verifyChannel,
  type Channel,
  type ChannelsOverview,
  type QueueEntry,
} from "@/lib/channels";
import { readableApiError } from "@/lib/readable-error";
import { useSession } from "@/src/shared/auth";
import { useLaunchStatus } from "@/src/shared/hooks";

function formatWhen(iso: string | null): string {
  if (!iso) return "Not scheduled";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
}

function QueueRow({ entry }: Readonly<{ entry: QueueEntry }>) {
  const failed = entry.status === "failed";
  return (
    <View style={ui.card}>
      <View style={ui.row}>
        <Text style={ui.title}>{entry.channel_label || entry.labels.join(", ") || "Channel post"}</Text>
        <View style={[ui.badge, failed ? ui.badgeDanger : entry.status === "published" ? ui.badgeOk : null]}>
          <Text style={[ui.badgeText, failed ? ui.badgeDangerText : entry.status === "published" ? ui.badgeOkText : null]}>
            {entry.status}
          </Text>
        </View>
      </View>
      <Text style={ui.muted}>{formatWhen(entry.scheduled_at)}</Text>
      {entry.text ? <Text style={ui.body} numberOfLines={3}>{entry.text}</Text> : null}
      {entry.error ? <Text style={ui.error}>{entry.error}</Text> : null}
      {entry.url ? (
        <Pressable onPress={() => void Linking.openURL(entry.url)} accessibilityRole="link">
          <Text style={[ui.muted, { textDecorationLine: "underline" }]}>View post</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

export default function CalendarChannelsScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const launch = useLaunchStatus(token);
  const publishingOpen = launch.status ? launch.status.features.publishing : launch.loading ? null : false;

  const [data, setData] = useState<ChannelsOverview | null>(null);
  const [queue, setQueue] = useState<QueueEntry[]>([]);
  const [queueError, setQueueError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, RowNote>>({});
  const [nonce, setNonce] = useState(0);

  const loadQueue = useCallback(
    async (channels: readonly Channel[]) => {
      try {
        setQueue(await getChannelQueue(new Set(channels.map((c) => c.id)), { token }));
        setQueueError("");
      } catch (err) {
        setQueueError(readableApiError(err, "Couldn't load the post queue."));
      }
    },
    [token],
  );

  useEffect(() => {
    let active = true;
    setLoading(true);
    getChannels({ token })
      .then(async (overview) => {
        if (!active) return;
        setData(overview);
        setLoadError("");
        await loadQueue(overview.channels);
      })
      .catch((err: unknown) => {
        if (active) setLoadError(readableApiError(err, "Couldn't load your channels."));
      })
      .finally(() => {
        if (!active) return;
        setLoading(false);
        setRefreshing(false);
      });
    return () => {
      active = false;
    };
  }, [token, nonce, loadQueue]);

  const channels = useMemo(() => data?.channels ?? [], [data]);

  const replace = (next: Channel) =>
    setData((prev) => (prev ? { ...prev, channels: prev.channels.map((c) => (c.id === next.id ? next : c)) } : prev));
  const note = (id: string, value: RowNote) => setNotes((prev) => ({ ...prev, [id]: value }));

  const run = useCallback(
    async (id: string, action: ChannelAction) => {
      setBusy(`${action}:${id}`);
      try {
        if (action === "verify") {
          const updated = await verifyChannel(id, { token });
          replace(updated);
          note(id, updated.last_error ? { tone: "error", text: updated.last_error } : { tone: "ok", text: "The credential still works." });
        } else if (action === "test") {
          const post = await testChannel(id, "", { token });
          note(
            id,
            post.status === "published"
              ? { tone: "ok", text: "Test post sent.", url: post.url }
              : { tone: "error", text: post.error || `The test post is ${post.status}.` },
          );
        } else {
          const result = await disconnectChannel(id, { token });
          setData((prev) => (prev ? { ...prev, channels: prev.channels.filter((c) => c.id !== id) } : prev));
          if (result.canceled_posts > 0) {
            Alert.alert("Channel disconnected", `${result.canceled_posts} scheduled post(s) to that channel were canceled.`);
          }
          setNonce((n) => n + 1);
        }
      } catch (err) {
        note(id, { tone: "error", text: readableApiError(err, "That did not work. Try again.") });
      } finally {
        setBusy(null);
      }
    },
    [token],
  );

  const onAction = useCallback(
    (id: string, action: ChannelAction) => {
      if (action !== "remove") {
        void run(id, action);
        return;
      }
      Alert.alert("Disconnect this channel?", "Posts not yet sent to it are canceled.", [
        { text: "Cancel", style: "cancel" },
        { text: "Disconnect", style: "destructive", onPress: () => void run(id, "remove") },
      ]);
    },
    [run],
  );

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    setNonce((n) => n + 1);
    launch.refresh();
  }, [launch]);

  return (
    <ScrollView
      style={ui.screen}
      contentContainerStyle={ui.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />}
    >
      <Stack.Screen options={{ title: "Channels" }} />
      <Text style={ui.intro}>
        Telegram channels and groups, Discord channels and Mastodon accounts. Their APIs are free and need no
        platform review, so a connected channel works right away. Credentials are encrypted and never shown again.
      </Text>
      <LaunchStatusBanner status={launch.status} gate="publishing" />

      {loading && !data ? (
        <View style={ui.center}>
          <ActivityIndicator color={colors.accent} />
          <Text style={ui.muted}>Loading your channels</Text>
        </View>
      ) : loadError && !data ? (
        <View style={ui.card}>
          <Text style={ui.error}>{loadError}</Text>
          <ActionButton label="Try again" variant="ghost" icon="refresh" onPress={() => setNonce((n) => n + 1)} />
        </View>
      ) : (
        <>
          <Text style={ui.sectionTitle}>Post to channels</Text>
          <ChannelComposer
            channels={channels}
            token={token}
            publishingOpen={publishingOpen}
            onPosted={() => void loadQueue(channels)}
          />

          <Text style={ui.sectionTitle}>Queue</Text>
          {queueError ? <Text style={ui.error}>{queueError}</Text> : null}
          {queue.length === 0 && !queueError ? (
            <View style={ui.empty}>
              <Text style={ui.muted}>No channel posts in the last week or the next two months.</Text>
            </View>
          ) : (
            queue.map((entry) => <QueueRow key={`${entry.source}:${entry.id}`} entry={entry} />)
          )}

          <Text style={ui.sectionTitle}>Connected channels</Text>
          {channels.length === 0 ? (
            <View style={ui.empty}>
              <Text style={ui.muted}>
                Nothing connected yet. Add a channel below; each one is checked against the platform before it is saved.
              </Text>
            </View>
          ) : (
            channels.map((c) => <ChannelRow key={c.id} channel={c} busy={busy} note={notes[c.id]} onAction={onAction} />)
          )}

          <Text style={ui.sectionTitle}>Add a channel</Text>
          <ConnectChannelForm
            kinds={data?.kinds ?? []}
            token={token}
            onConnected={(channel) =>
              setData((prev) => {
                if (!prev) return prev;
                const rest = prev.channels.filter((c) => c.id !== channel.id);
                return { ...prev, channels: [...rest, channel] };
              })
            }
          />
        </>
      )}
    </ScrollView>
  );
}
