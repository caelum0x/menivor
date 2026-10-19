/**
 * Route: /inbox/[id] — one social inbox thread. Read the conversation, get
 * reply suggestions, and reply in the app when the platform lets Menivor post
 * replies. Where it does not (or sending is off on this server), the screen
 * says so, opens the post on the platform, and lets the creator mark the
 * thread replied or done afterwards.
 *
 * Backed by GET /social-inbox/threads/{id}, POST …/suggestions, POST …/reply
 * and POST …/status (plus GET /social-inbox for the server's sending switch).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Linking,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { Stack, useLocalSearchParams } from "expo-router";

import { ApiError } from "@/src/shared/api";
import { useSession } from "@/src/shared/auth";
import { colors, radius, spacing, typeScale } from "@/src/shared/theme";
import { Button, ErrorState, TextField } from "@/components/ui";
import {
  MAX_REPLY_CHARS,
  STATUS_LABEL,
  getInboxOverview,
  getThread,
  readableApiMessage,
  relativeTime,
  replyAffordance,
  sendReply,
  setThreadStatus,
  suggestReplies,
  validateReply,
  type InboxThreadDetail,
  type ThreadStatus,
} from "@/lib/social-inbox";

function describe(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 404) return "This conversation no longer exists.";
    if (err.status === 429) return "Too many requests. Wait a minute and try again.";
    return readableApiMessage(err.message, fallback);
  }
  return err instanceof Error ? err.message : fallback;
}

export default function InboxThreadScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const threadId = String(id ?? "");
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const [thread, setThread] = useState<InboxThreadDetail | null>(null);
  const [sendingEnabled, setSendingEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState<"" | "send" | "suggest" | ThreadStatus>("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<readonly string[]>([]);

  const load = useCallback(async () => {
    if (!threadId) return;
    setError(null);
    try {
      const [detail, overview] = await Promise.all([
        getThread(threadId, { token }),
        getInboxOverview({ token }).catch(() => null),
      ]);
      setThread(detail);
      setSendingEnabled(Boolean(overview?.sending_enabled));
    } catch (err) {
      setError(describe(err, "Could not load this conversation."));
    }
  }, [threadId, token]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    load().finally(() => {
      if (active) setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [load]);

  const affordance = useMemo(
    () => (thread ? replyAffordance(thread, sendingEnabled) : null),
    [thread, sendingEnabled],
  );

  const onSuggest = useCallback(async () => {
    setBusy("suggest");
    setActionError(null);
    try {
      const result = await suggestReplies(threadId, { token });
      setSuggestions(result.suggestions);
    } catch (err) {
      setActionError(describe(err, "Could not get suggestions."));
    } finally {
      setBusy("");
    }
  }, [threadId, token]);

  const onSend = useCallback(async () => {
    const checked = validateReply(draft);
    if (!checked.ok) {
      setActionError(checked.error);
      return;
    }
    setBusy("send");
    setActionError(null);
    try {
      const updated = await sendReply(threadId, checked.text, { token });
      setThread(updated);
      setDraft("");
      setSuggestions([]);
    } catch (err) {
      setActionError(describe(err, "The reply was not sent."));
    } finally {
      setBusy("");
    }
  }, [draft, threadId, token]);

  const onStatus = useCallback(
    async (status: ThreadStatus) => {
      setBusy(status);
      setActionError(null);
      try {
        const updated = await setThreadStatus(threadId, status, status === "replied" ? draft : "", { token });
        setThread(updated);
        if (status === "replied") setDraft("");
      } catch (err) {
        setActionError(describe(err, "Could not update the thread."));
      } finally {
        setBusy("");
      }
    },
    [draft, threadId, token],
  );

  const onOpen = useCallback(async () => {
    const url = affordance?.openUrl;
    if (!url) return;
    try {
      await Linking.openURL(url);
    } catch {
      setActionError("Could not open the post on the platform.");
    }
  }, [affordance]);

  if (loading) {
    return (
      <View style={styles.center}>
        <Stack.Screen options={{ title: "Conversation" }} />
        <ActivityIndicator color={colors.accent} />
      </View>
    );
  }

  if (!thread || !affordance) {
    return (
      <View style={styles.center}>
        <Stack.Screen options={{ title: "Conversation" }} />
        <ErrorState message={error ?? "Could not load this conversation."} onRetry={load} />
      </View>
    );
  }

  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      keyboardVerticalOffset={88}
    >
      <Stack.Screen options={{ title: thread.platform_label || "Conversation" }} />
      <ScrollView style={styles.flex} contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <View style={styles.meta}>
          <Text style={styles.title}>{thread.author_name || "Someone"}</Text>
          <Text style={styles.faint}>
            {thread.kind === "dm" ? "Message" : "Comment"} · {STATUS_LABEL[thread.status]}
            {thread.post_title ? ` · On: ${thread.post_title}` : ""}
          </Text>
        </View>

        {thread.messages.map((m) => (
          <View key={m.id} style={[styles.bubble, m.from_me ? styles.mine : styles.theirs]}>
            <Text style={styles.bubbleAuthor}>{m.from_me ? "You" : m.author || thread.author_name}</Text>
            <Text style={styles.bubbleText}>{m.text}</Text>
            <Text style={styles.faint}>
              {relativeTime(m.at)}
              {m.from_me && m.via ? ` · via ${m.via}` : ""}
            </Text>
          </View>
        ))}

        <View style={styles.composer}>
          {affordance.note ? <Text style={styles.note}>{affordance.note}</Text> : null}
          <TextField
            label={affordance.canSendInApp ? "Your reply" : "Your reply (to note what you sent)"}
            value={draft}
            onChangeText={setDraft}
            placeholder="Write a reply"
            multiline
            numberOfLines={4}
            maxLength={MAX_REPLY_CHARS}
            helper={`${draft.trim().length}/${MAX_REPLY_CHARS}`}
          />
          {suggestions.length > 0 ? (
            <View style={styles.suggestions}>
              {suggestions.map((s) => (
                <Pressable
                  key={s}
                  style={({ pressed }) => [styles.suggestion, pressed && styles.pressed]}
                  onPress={() => setDraft(s)}
                  accessibilityRole="button"
                  accessibilityLabel={`Use suggestion: ${s}`}
                >
                  <Text style={styles.suggestionText}>{s}</Text>
                </Pressable>
              ))}
            </View>
          ) : null}
          {actionError ? <Text style={styles.error}>{actionError}</Text> : null}
          <View style={styles.actions}>
            <Button
              label="Suggest replies"
              variant="ghost"
              size="sm"
              loading={busy === "suggest"}
              disabled={busy !== ""}
              onPress={onSuggest}
            />
            {affordance.canSendInApp ? (
              <Button
                label="Send reply"
                size="sm"
                loading={busy === "send"}
                disabled={busy !== "" || !draft.trim()}
                onPress={onSend}
              />
            ) : affordance.openUrl ? (
              <Button label="Open on platform" variant="secondary" size="sm" onPress={onOpen} />
            ) : null}
          </View>
          <View style={styles.actions}>
            {thread.status !== "replied" ? (
              <Button
                label="Mark replied"
                variant="secondary"
                size="sm"
                loading={busy === "replied"}
                disabled={busy !== ""}
                onPress={() => onStatus("replied")}
              />
            ) : null}
            {thread.status !== "done" ? (
              <Button
                label="Mark done"
                variant="secondary"
                size="sm"
                loading={busy === "done"}
                disabled={busy !== ""}
                onPress={() => onStatus("done")}
              />
            ) : null}
            {thread.status !== "needs_reply" ? (
              <Button
                label="Reopen"
                variant="ghost"
                size="sm"
                loading={busy === "needs_reply"}
                disabled={busy !== ""}
                onPress={() => onStatus("needs_reply")}
              />
            ) : null}
          </View>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bg },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.bg, padding: spacing.lg },
  content: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xxl },
  meta: { gap: spacing.xs },
  title: { color: colors.textPrimary, fontSize: typeScale.heading, fontWeight: "700" },
  faint: { color: colors.textFaint, fontSize: typeScale.micro },
  bubble: {
    borderRadius: radius.lg,
    padding: spacing.md,
    gap: spacing.xs,
    maxWidth: "88%",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  theirs: { alignSelf: "flex-start", backgroundColor: colors.surface },
  mine: { alignSelf: "flex-end", backgroundColor: colors.surfaceAlt },
  bubbleAuthor: { color: colors.textSecondary, fontSize: typeScale.micro, fontWeight: "600" },
  bubbleText: { color: colors.textPrimary, fontSize: typeScale.body, lineHeight: 21 },
  composer: { gap: spacing.sm, marginTop: spacing.md },
  note: { color: colors.textSecondary, fontSize: typeScale.caption, lineHeight: 18 },
  suggestions: { gap: spacing.sm },
  suggestion: {
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.sm,
    backgroundColor: colors.surface,
  },
  suggestionText: { color: colors.textPrimary, fontSize: typeScale.caption, lineHeight: 18 },
  pressed: { opacity: 0.7 },
  error: { color: colors.danger, fontSize: typeScale.caption },
  actions: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
});
