/**
 * Route: /catalog/reddit-story — turn a Reddit thread into a story-reel draft.
 *
 * NAV MANIFEST (routes for the integration agent to wire into navigation):
 *   { route: "/catalog/reddit-story", title: "Reddit Story" }
 *
 * The Reddit story-to-reel source (POST /stories/reddit): paste a Reddit thread
 * URL, optionally override the subject/title and pick a narration voice, and the
 * backend fetches + narrates the thread and returns a template-bound reel draft
 * (the minecraft-reddit-split split preset over the looping parkour background).
 * The screen previews the cleaned thread + the ready-to-submit draft so the
 * creator can confirm the hook and script before spending credits; submission
 * happens from Create (this flow is stateless — no job is created here).
 *
 * States: idle form (with client-side URL validation), loading, error+retry,
 * and a rich result with thread + draft preview and a confirmed "start over".
 *
 * Auth flows through the shared api client (x-api-key). No secrets here.
 */

import type { ReactElement } from "react";
import { useCallback, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { Stack } from "expo-router";

import { ApiError } from "@/src/shared/api";
import { useSession } from "@/src/shared/auth";
import { colors, radius, spacing, typeScale, weight } from "@/src/shared/theme";
import {
  bodyWordCount,
  createRedditStory,
  draftScript,
  looksLikeRedditUrl,
  looksLikeUrl,
  storyDraftSubject,
  threadAttribution,
  type RedditStoryResult,
} from "@/lib/stories";

const SUBJECT_MAX = 120;
const VOICE_MAX = 64;
const BODY_PREVIEW_CHARS = 480;

export default function RedditStoryScreen(): ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const [url, setUrl] = useState("");
  const [subject, setSubject] = useState("");
  const [voiceId, setVoiceId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RedditStoryResult | null>(null);

  const trimmedUrl = url.trim();
  const isUrl = looksLikeUrl(trimmedUrl);
  const isReddit = looksLikeRedditUrl(trimmedUrl);
  const canSubmit = isReddit && !busy;

  const onSubmit = useCallback(async () => {
    const target = url.trim();
    if (!looksLikeRedditUrl(target)) {
      setError("Enter a valid Reddit thread URL (reddit.com or redd.it).");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const created = await createRedditStory(
        {
          url: target,
          subject: subject.trim() || undefined,
          voice_id: voiceId.trim() || undefined,
        },
        { token },
      );
      setResult(created);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not turn that thread into a story. Check the URL and try again.",
      );
    } finally {
      setBusy(false);
    }
  }, [url, subject, voiceId, token]);

  const onStartOver = useCallback(() => {
    Alert.alert(
      "Start over",
      "Discard this generated story draft and enter a new thread?",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Start over",
          style: "destructive",
          onPress: () => {
            setResult(null);
            setError(null);
            setUrl("");
            setSubject("");
            setVoiceId("");
          },
        },
      ],
    );
  }, []);

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
    >
      <Stack.Screen options={{ title: "Reddit Story" }} />

      <Text style={styles.intro}>
        Paste a Reddit thread URL. We fetch and clean the post, narrate it, and
        draft a story reel on the split-screen parkour preset — ready to submit
        from Create.
      </Text>

      {result ? (
        <StoryResult result={result} onStartOver={onStartOver} />
      ) : (
        <StoryForm
          url={url}
          subject={subject}
          voiceId={voiceId}
          busy={busy}
          isUrl={isUrl}
          isReddit={isReddit}
          trimmedUrl={trimmedUrl}
          canSubmit={canSubmit}
          error={error}
          onChangeUrl={setUrl}
          onChangeSubject={setSubject}
          onChangeVoiceId={setVoiceId}
          onSubmit={onSubmit}
        />
      )}

      <View style={styles.spacer} />
    </ScrollView>
  );
}

// ---------------------------------------------------------------------------
// Form
// ---------------------------------------------------------------------------

interface StoryFormProps {
  readonly url: string;
  readonly subject: string;
  readonly voiceId: string;
  readonly busy: boolean;
  readonly isUrl: boolean;
  readonly isReddit: boolean;
  readonly trimmedUrl: string;
  readonly canSubmit: boolean;
  readonly error: string | null;
  readonly onChangeUrl: (value: string) => void;
  readonly onChangeSubject: (value: string) => void;
  readonly onChangeVoiceId: (value: string) => void;
  readonly onSubmit: () => void;
}

function StoryForm({
  url,
  subject,
  voiceId,
  busy,
  isUrl,
  isReddit,
  trimmedUrl,
  canSubmit,
  error,
  onChangeUrl,
  onChangeSubject,
  onChangeVoiceId,
  onSubmit,
}: StoryFormProps): ReactElement {
  const urlWarn =
    trimmedUrl.length > 0 && !isUrl
      ? "That does not look like an http(s) URL."
      : trimmedUrl.length > 0 && !isReddit
        ? "That is a URL, but not a reddit.com / redd.it thread."
        : null;

  return (
    <View style={styles.form}>
      <Text style={styles.label}>Reddit thread URL</Text>
      <TextInput
        style={styles.input}
        value={url}
        onChangeText={onChangeUrl}
        placeholder="https://www.reddit.com/r/AmItheAsshole/comments/…"
        placeholderTextColor={colors.textFaint}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="url"
        editable={!busy}
        accessibilityLabel="Reddit thread URL"
      />
      {urlWarn ? <Text style={styles.warn}>{urlWarn}</Text> : null}

      <Text style={styles.label}>Subject override (optional)</Text>
      <TextInput
        style={styles.input}
        value={subject}
        onChangeText={onChangeSubject}
        placeholder="Leave blank to use the thread title"
        placeholderTextColor={colors.textFaint}
        maxLength={SUBJECT_MAX}
        editable={!busy}
        accessibilityLabel="Subject override"
      />

      <Text style={styles.label}>Narration voice id (optional)</Text>
      <TextInput
        style={styles.input}
        value={voiceId}
        onChangeText={onChangeVoiceId}
        placeholder="ElevenLabs voice id, e.g. rachel"
        placeholderTextColor={colors.textFaint}
        autoCapitalize="none"
        autoCorrect={false}
        maxLength={VOICE_MAX}
        editable={!busy}
        accessibilityLabel="Narration voice id"
      />
      <Text style={styles.hint}>
        Leave the voice blank to use the default narrator.
      </Text>

      <Pressable
        style={[styles.submit, !canSubmit && styles.submitDim]}
        onPress={onSubmit}
        disabled={!canSubmit}
        accessibilityRole="button"
        accessibilityLabel="Turn this Reddit thread into a story reel draft"
        accessibilityState={{ busy, disabled: !canSubmit }}
      >
        {busy ? (
          <ActivityIndicator color={colors.onAccent} />
        ) : (
          <Text style={styles.submitText}>Generate story draft</Text>
        )}
      </Pressable>

      {error ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Result
// ---------------------------------------------------------------------------

interface StoryResultProps {
  readonly result: RedditStoryResult;
  readonly onStartOver: () => void;
}

function StoryResult({ result, onStartOver }: StoryResultProps): ReactElement {
  const { thread, reel_draft } = result;
  const attribution = threadAttribution(thread);
  const words = bodyWordCount(thread.body);
  const script = draftScript(reel_draft);

  const bodyPreview = useMemo<string>(() => {
    const body = (thread.body ?? "").trim();
    if (body.length <= BODY_PREVIEW_CHARS) return body;
    return `${body.slice(0, BODY_PREVIEW_CHARS).trimEnd()}…`;
  }, [thread.body]);

  return (
    <View style={styles.resultBlock}>
      <View style={styles.threadCard}>
        <Text style={styles.kicker}>REDDIT THREAD</Text>
        {thread.title ? (
          <Text style={styles.threadTitle}>{thread.title}</Text>
        ) : null}
        {attribution ? (
          <Text style={styles.attribution}>{attribution}</Text>
        ) : null}
        {bodyPreview ? (
          <Text style={styles.threadBody}>{bodyPreview}</Text>
        ) : null}
        {words > 0 ? (
          <Text style={styles.metaLine}>{words} words in the story body</Text>
        ) : null}

        {thread.top_comments.length > 0 ? (
          <View style={styles.comments}>
            <Text style={styles.commentsTitle}>
              Top comments ({thread.top_comments.length})
            </Text>
            {thread.top_comments.map((comment, index) => (
              <Text key={`${index}-${comment.slice(0, 16)}`} style={styles.comment}>
                {comment}
              </Text>
            ))}
          </View>
        ) : null}
      </View>

      <View style={styles.draftCard}>
        <Text style={styles.draftKicker}>REEL DRAFT · READY TO SUBMIT</Text>
        <Text style={styles.draftSubject}>{storyDraftSubject(result)}</Text>

        <View style={styles.chipRow}>
          {reel_draft.layout ? (
            <Chip label={`Layout · ${reel_draft.layout}`} />
          ) : null}
          {reel_draft.caption_style ? (
            <Chip label={`Captions · ${reel_draft.caption_style}`} />
          ) : null}
          {reel_draft.aspect ? (
            <Chip label={`Aspect · ${reel_draft.aspect}`} />
          ) : null}
          {reel_draft.background_id ? (
            <Chip label={`Background · ${reel_draft.background_id}`} />
          ) : null}
          {reel_draft.voice_name ? (
            <Chip label={`Voice · ${reel_draft.voice_name}`} />
          ) : null}
        </View>

        {script ? (
          <>
            <Text style={styles.scriptLabel}>NARRATION SCRIPT</Text>
            <Text style={styles.script}>{script}</Text>
          </>
        ) : (
          <Text style={styles.scriptEmpty}>
            No script text — the pipeline will write the narration from the
            subject when you submit.
          </Text>
        )}
      </View>

      <Text style={styles.hint}>
        Head to Create to submit this draft to the reel pipeline. Nothing has
        been rendered yet — no credits have been spent.
      </Text>

      <Pressable
        style={styles.startOver}
        onPress={onStartOver}
        accessibilityRole="button"
        accessibilityLabel="Discard this draft and start over"
      >
        <Text style={styles.startOverText}>Start over</Text>
      </Pressable>
    </View>
  );
}

function Chip({ label }: { readonly label: string }): ReactElement {
  return (
    <View style={styles.chip}>
      <Text style={styles.chipText}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.lg, gap: spacing.sm },
  intro: {
    color: colors.textSecondary,
    fontSize: typeScale.caption,
    lineHeight: 20,
    marginBottom: spacing.sm,
  },
  form: { gap: spacing.sm },
  label: {
    color: colors.textPrimary,
    fontSize: typeScale.caption,
    fontWeight: weight.semibold,
    marginTop: spacing.xs,
    marginBottom: spacing.xs,
  },
  input: {
    backgroundColor: colors.input,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm + 2,
    color: colors.textPrimary,
    fontSize: typeScale.body,
  },
  warn: { color: colors.danger, fontSize: typeScale.micro, marginTop: spacing.xs },
  submit: {
    backgroundColor: colors.accent,
    borderRadius: radius.md,
    paddingVertical: spacing.md,
    alignItems: "center",
    justifyContent: "center",
    minHeight: 48,
    marginTop: spacing.md,
  },
  submitDim: { opacity: 0.45 },
  submitText: {
    color: colors.onAccent,
    fontSize: typeScale.body,
    fontWeight: weight.bold,
  },
  error: {
    color: colors.danger,
    fontSize: typeScale.caption,
    lineHeight: 18,
    marginTop: spacing.xs,
  },
  resultBlock: { gap: spacing.md },
  threadCard: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.lg,
    padding: spacing.md,
    gap: spacing.xs,
  },
  kicker: {
    color: colors.textFaint,
    fontSize: typeScale.micro,
    fontWeight: weight.bold,
    letterSpacing: 1,
  },
  threadTitle: {
    color: colors.textPrimary,
    fontSize: typeScale.subheading,
    fontWeight: weight.bold,
    marginTop: spacing.xs,
  },
  attribution: { color: colors.accent, fontSize: typeScale.micro, fontWeight: weight.semibold },
  threadBody: {
    color: colors.textSecondary,
    fontSize: typeScale.caption,
    lineHeight: 19,
    marginTop: spacing.xs,
  },
  metaLine: { color: colors.textFaint, fontSize: typeScale.micro, marginTop: spacing.xs },
  comments: { marginTop: spacing.sm, gap: spacing.xs },
  commentsTitle: {
    color: colors.textPrimary,
    fontSize: typeScale.caption,
    fontWeight: weight.semibold,
  },
  comment: {
    color: colors.textFaint,
    fontSize: typeScale.micro,
    lineHeight: 16,
  },
  draftCard: {
    backgroundColor: colors.surfaceAlt,
    borderColor: colors.accent,
    borderWidth: 1,
    borderRadius: radius.lg,
    padding: spacing.md,
    gap: spacing.xs,
  },
  draftKicker: {
    color: colors.accent,
    fontSize: typeScale.micro,
    fontWeight: weight.bold,
    letterSpacing: 1,
  },
  draftSubject: {
    color: colors.textPrimary,
    fontSize: typeScale.subheading,
    fontWeight: weight.bold,
    marginTop: spacing.xs,
  },
  chipRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.xs,
    marginTop: spacing.xs,
  },
  chip: {
    backgroundColor: colors.surfaceMuted,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
  },
  chipText: { color: colors.textSecondary, fontSize: typeScale.micro, fontWeight: weight.medium },
  scriptLabel: {
    color: colors.textFaint,
    fontSize: typeScale.micro,
    fontWeight: weight.bold,
    letterSpacing: 1,
    marginTop: spacing.sm,
  },
  script: {
    color: colors.textSecondary,
    fontSize: typeScale.caption,
    lineHeight: 19,
  },
  scriptEmpty: {
    color: colors.textFaint,
    fontSize: typeScale.micro,
    lineHeight: 16,
    marginTop: spacing.sm,
  },
  hint: { color: colors.textFaint, fontSize: typeScale.micro, lineHeight: 16 },
  startOver: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingVertical: spacing.sm + 2,
    alignItems: "center",
    justifyContent: "center",
    marginTop: spacing.xs,
  },
  startOverText: { color: colors.textSecondary, fontSize: typeScale.body, fontWeight: weight.semibold },
  spacer: { height: 48 },
});
