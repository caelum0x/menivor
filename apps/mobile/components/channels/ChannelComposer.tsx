/**
 * Post to one or more connected channels now, or schedule it for later
 * (POST /publishing/channel-posts). Follows the publishing launch gate; the API
 * enforces the same gate and per-channel caption limits (409 `problems`).
 */

import { useMemo, useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";

import { ActionButton } from "@/components/approvals/Button";
import { ui } from "@/components/approvals/styles";
import { colors } from "@/components/me/theme";
import { DateTimeField } from "@/components/schedule/DateTimeField";
import { defaultScheduleAt } from "@/components/schedule/datetime";
import {
  CAPTION_MAX,
  MAX_CHANNELS_PER_POST,
  buildPostsInput,
  checkCompose,
  createChannelPosts,
  parseHashtags,
  problemsOf,
  type Channel,
  type ChannelPost,
} from "@/lib/channels";
import { readableApiError } from "@/lib/readable-error";

export interface ChannelComposerProps {
  channels: readonly Channel[];
  token?: string;
  /** Publishing launch gate; null while loading. */
  publishingOpen: boolean | null;
  onPosted: (posts: ChannelPost[]) => void;
}

export function ChannelComposer({ channels, token, publishingOpen, onPosted }: Readonly<ChannelComposerProps>) {
  const postable = useMemo(() => channels.filter((c) => c.can_post), [channels]);
  const [selectedIds, setSelectedIds] = useState<ReadonlySet<string>>(new Set());
  const [caption, setCaption] = useState("");
  const [tags, setTags] = useState("");
  const [later, setLater] = useState(false);
  const [when, setWhen] = useState<Date | null>(() => defaultScheduleAt());
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [problems, setProblems] = useState<string[]>([]);
  const [done, setDone] = useState("");

  const selected = postable.filter((c) => selectedIds.has(c.id));
  const scheduledAt = later ? when : null;
  const check = checkCompose(selected, caption, scheduledAt);
  const gateClosed = publishingOpen === false;

  const toggle = (id: string) =>
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const send = async () => {
    if (!check.ok) {
      setError(check.reason);
      return;
    }
    if (later && !when) {
      setError("Enter a valid date and time.");
      return;
    }
    setSending(true);
    setError("");
    setProblems([]);
    setDone("");
    try {
      const posts = await createChannelPosts(buildPostsInput(selected, caption, parseHashtags(tags), scheduledAt), {
        token,
      });
      const failed = posts.filter((p) => p.status === "failed");
      setDone(
        later
          ? `Scheduled for ${selected.length} channel${selected.length === 1 ? "" : "s"}.`
          : failed.length
            ? `${posts.length - failed.length} of ${posts.length} sent. Check the queue for the error.`
            : `Posted to ${posts.length} channel${posts.length === 1 ? "" : "s"}.`,
      );
      setCaption("");
      setTags("");
      onPosted(posts);
    } catch (err) {
      const listed = problemsOf(err).map((p) => {
        const label = channels.find((c) => c.id === p.channel_id)?.label;
        return label ? `${label}: ${p.message}` : p.message;
      });
      setProblems(listed);
      setError(readableApiError(err, "Couldn't post. Nothing was sent."));
    } finally {
      setSending(false);
    }
  };

  if (postable.length === 0) {
    return (
      <View style={ui.empty}>
        <Text style={ui.muted}>Connect a channel below to post to it from here.</Text>
      </View>
    );
  }

  return (
    <View style={ui.card}>
      <Text style={ui.kicker}>Post to (up to {MAX_CHANNELS_PER_POST})</Text>
      <View style={ui.row}>
        {postable.map((c) => {
          const on = selectedIds.has(c.id);
          return (
            <Pressable
              key={c.id}
              onPress={() => toggle(c.id)}
              style={[ui.chip, on && ui.chipOn]}
              accessibilityRole="checkbox"
              accessibilityState={{ checked: on }}
            >
              <Text style={[ui.chipText, on && ui.chipTextOn]}>
                {c.label} ({c.kind_label})
              </Text>
            </Pressable>
          );
        })}
      </View>

      <TextInput
        style={[ui.input, ui.multiline]}
        value={caption}
        onChangeText={setCaption}
        maxLength={CAPTION_MAX}
        multiline
        placeholder="What do you want to post?"
        placeholderTextColor={colors.muted}
        editable={!sending}
        accessibilityLabel="Post text"
      />
      <TextInput
        style={ui.input}
        value={tags}
        onChangeText={setTags}
        placeholder="Hashtags, e.g. #mobilegame launch"
        placeholderTextColor={colors.muted}
        autoCapitalize="none"
        editable={!sending}
        accessibilityLabel="Hashtags"
      />

      <View style={ui.row}>
        <Pressable onPress={() => setLater(false)} style={[ui.chip, !later && ui.chipOn]}
          accessibilityRole="radio" accessibilityState={{ selected: !later }}>
          <Text style={[ui.chipText, !later && ui.chipTextOn]}>Post now</Text>
        </Pressable>
        <Pressable onPress={() => setLater(true)} style={[ui.chip, later && ui.chipOn]}
          accessibilityRole="radio" accessibilityState={{ selected: later }}>
          <Text style={[ui.chipText, later && ui.chipTextOn]}>Schedule</Text>
        </Pressable>
      </View>
      {later ? <DateTimeField initialDate={when ?? defaultScheduleAt()} onChange={setWhen} disabled={sending} /> : null}

      {gateClosed ? (
        <Text style={ui.muted}>Publishing is not open yet, so posting is disabled. Connecting and test checks still work.</Text>
      ) : null}
      {!check.ok && (selected.length > 0 || caption.length > 0) ? <Text style={ui.muted}>{check.reason}</Text> : null}

      <ActionButton
        label={later ? "Schedule post" : "Post now"}
        icon={later ? "time-outline" : "send"}
        onPress={() => void send()}
        busy={sending}
        disabled={!check.ok || gateClosed || publishingOpen === null}
      />
      {error ? <Text style={ui.error} accessibilityRole="alert">{error}</Text> : null}
      {problems.map((p) => (
        <Text key={p} style={ui.error}>{p}</Text>
      ))}
      {done ? <Text style={ui.ok}>{done}</Text> : null}
    </View>
  );
}
