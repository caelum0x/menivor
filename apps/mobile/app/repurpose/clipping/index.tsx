/**
 * Route: /repurpose/clipping — the CONTENT ENGINE home (long-form → shorts).
 *
 * NAV MANIFEST (for the integration agent to register in navigation):
 *   { route: "/repurpose/clipping",          title: "Content Engine" }
 *   { route: "/repurpose/clipping/[id]",      title: "Repurpose Job" }
 *   { route: "/repurpose/clipping/clip/[id]", title: "Auto-Clip Job" }
 *   { route: "/repurpose/clipping/ingest",    title: "Import from URL" }
 *
 * Submit a long recording (R2 upload key) or a public video URL to one of two
 * engines — the "Repurpose" ranker (transcript → AI-scored highlight clips you
 * review + promote) or the fire-and-forget "Auto-clip" worker (several vertical
 * caption-burned shorts). Both engines' jobs are listed here with pull-to-
 * refresh and refresh-on-focus; tapping a job opens its detail. A shortcut opens
 * the URL-import flow. Full loading / empty / error states throughout.
 *
 * Auth flows through the shared api client (x-api-key); create requests carry an
 * Idempotency-Key. No secrets here.
 */

import { useCallback, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { Stack, useFocusEffect, useRouter } from "expo-router";

import { ApiError } from "@/src/shared/api";
import { useSession } from "@/src/shared/auth";
import { colors, radius, spacing, typeScale, weight } from "@/src/shared/theme";
import {
  createClipJob,
  createRepurposeJob,
  formatJobDate,
  listClipJobs,
  listRepurposeJobs,
  looksLikeUrl,
  repurposeJobTitle,
  statusColor,
  type ClipJob,
  type RepurposeJob,
} from "@/lib/repurpose";

import { StatusPill } from "@/src/features/repurpose/components/StatusPill";
import { GenerationErrorNotice } from "@/components/billing/GenerationErrorNotice";

type Engine = "repurpose" | "autoclip";

function newIdempotencyKey(): string {
  return `repurpose-${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
}

export default function ContentEngineScreen() {
  const { apiKey } = useSession();
  const router = useRouter();
  const token = apiKey ?? undefined;

  const [engine, setEngine] = useState<Engine>("repurpose");
  const [source, setSource] = useState("");
  const [title, setTitle] = useState("");

  const [repurposeJobs, setRepurposeJobs] = useState<RepurposeJob[]>([]);
  const [clipJobs, setClipJobs] = useState<ClipJob[]>([]);

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [listError, setListError] = useState<string | null>(null);

  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setListError(null);
    try {
      const [repurpose, clips] = await Promise.all([
        listRepurposeJobs({ token }),
        listClipJobs({ token }),
      ]);
      setRepurposeJobs(repurpose);
      setClipJobs(clips);
    } catch (err) {
      setListError(
        err instanceof ApiError ? err.message : "Failed to load your jobs.",
      );
    }
  }, [token]);

  useFocusEffect(
    useCallback(() => {
      let active = true;
      setLoading(true);
      load().finally(() => {
        if (active) setLoading(false);
      });
      return () => {
        active = false;
      };
    }, [load]),
  );

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  const trimmedSource = source.trim();
  const canSubmit = trimmedSource.length > 0 && !submitting;

  const onSubmit = useCallback(async () => {
    const ref = source.trim();
    if (!ref) {
      setFormError("Paste a video URL or an uploaded recording key first.");
      return;
    }
    setSubmitting(true);
    setFormError(null);
    const isUrl = looksLikeUrl(ref);
    try {
      if (engine === "repurpose") {
        const job = await createRepurposeJob(
          {
            source_kind: isUrl ? "url" : "upload",
            source_ref: ref,
            language: "auto",
            title: title.trim(),
          },
          { token, idempotencyKey: newIdempotencyKey() },
        );
        setSource("");
        setTitle("");
        await load();
        router.push(`/repurpose/clipping/${job.id}`);
      } else {
        const created = await createClipJob(
          isUrl ? { source_url: ref } : { source_video_key: ref },
          { token, idempotencyKey: newIdempotencyKey() },
        );
        setSource("");
        setTitle("");
        await load();
        router.push(`/repurpose/clipping/clip/${created.id}`);
      }
    } catch (err) {
      setFormError(
        err instanceof ApiError ? err.message : "Could not start the job.",
      );
    } finally {
      setSubmitting(false);
    }
  }, [engine, source, title, token, load, router]);

  const isEmpty = useMemo(
    () => repurposeJobs.length === 0 && clipJobs.length === 0,
    [repurposeJobs, clipJobs],
  );

  if (loading) {
    return (
      <View style={[styles.container, styles.center]}>
        <Stack.Screen options={{ title: "Content Engine" }} />
        <ActivityIndicator color={colors.accent} size="large" />
      </View>
    );
  }

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={onRefresh}
          tintColor={colors.accent}
        />
      }
    >
      <Stack.Screen options={{ title: "Content Engine" }} />

      <Text style={styles.intro}>
        Turn one long video into a batch of viral shorts. Paste a recording or a
        public video URL, pick an engine, and go.
      </Text>

      {/* Engine picker */}
      <View style={styles.segment}>
        <Pressable
          style={[styles.segmentBtn, engine === "repurpose" && styles.segmentActive]}
          onPress={() => setEngine("repurpose")}
          accessibilityRole="button"
          accessibilityState={{ selected: engine === "repurpose" }}
        >
          <Text
            style={[
              styles.segmentText,
              engine === "repurpose" && styles.segmentTextActive,
            ]}
          >
            AI highlights
          </Text>
        </Pressable>
        <Pressable
          style={[styles.segmentBtn, engine === "autoclip" && styles.segmentActive]}
          onPress={() => setEngine("autoclip")}
          accessibilityRole="button"
          accessibilityState={{ selected: engine === "autoclip" }}
        >
          <Text
            style={[
              styles.segmentText,
              engine === "autoclip" && styles.segmentTextActive,
            ]}
          >
            Auto-clip
          </Text>
        </Pressable>
      </View>
      <Text style={styles.engineHint}>
        {engine === "repurpose"
          ? "Rank the transcript into scored highlights you review, then promote the best into reels."
          : "A worker auto-produces several vertical, caption-burned shorts — hands-off."}
      </Text>

      <Text style={styles.label}>Recording key or video URL</Text>
      <TextInput
        style={styles.input}
        value={source}
        onChangeText={setSource}
        placeholder="https://… or an uploaded R2 key"
        placeholderTextColor={colors.textFaint}
        autoCapitalize="none"
        autoCorrect={false}
        editable={!submitting}
      />
      {trimmedSource.length > 0 ? (
        <Text style={styles.detectHint}>
          Detected source: {looksLikeUrl(trimmedSource) ? "external URL" : "uploaded recording"}
        </Text>
      ) : null}

      {engine === "repurpose" ? (
        <>
          <Text style={styles.label}>Title (optional)</Text>
          <TextInput
            style={styles.input}
            value={title}
            onChangeText={setTitle}
            placeholder="e.g. Podcast episode 42"
            placeholderTextColor={colors.textFaint}
            editable={!submitting}
          />
        </>
      ) : null}

      <Pressable
        style={[styles.submit, !canSubmit && styles.submitDim]}
        onPress={onSubmit}
        disabled={!canSubmit}
        accessibilityRole="button"
        accessibilityLabel="Start the content-engine job"
        accessibilityState={{ busy: submitting, disabled: !canSubmit }}
      >
        {submitting ? (
          <ActivityIndicator color={colors.onAccent} />
        ) : (
          <Text style={styles.submitText}>
            {engine === "repurpose" ? "Create repurpose job" : "Start auto-clip"}
          </Text>
        )}
      </Pressable>

      <Pressable
        style={styles.ingestLink}
        onPress={() => router.push("/repurpose/clipping/ingest")}
        accessibilityRole="button"
        accessibilityLabel="Import a reel draft from a web page URL"
      >
        <Text style={styles.ingestLinkText}>Import a reel from a web URL</Text>
      </Pressable>

      <GenerationErrorNotice message={formError} style={styles.error} />

      {/* Jobs */}
      <View style={styles.divider} />

      {listError ? (
        <View style={styles.errorBox}>
          <Text style={styles.error}>{listError}</Text>
          <Pressable style={styles.retryBtn} onPress={onRefresh}>
            <Text style={styles.retryText}>Retry</Text>
          </Pressable>
        </View>
      ) : null}

      {isEmpty && !listError ? (
        <Text style={styles.empty}>
          No jobs yet. Submit a long video above to build your first batch of
          shorts.
        </Text>
      ) : null}

      {repurposeJobs.length > 0 ? (
        <>
          <Text style={styles.sectionTitle}>AI highlight jobs</Text>
          {repurposeJobs.map((job) => (
            <Pressable
              key={job.id}
              style={styles.jobRow}
              onPress={() => router.push(`/repurpose/clipping/${job.id}`)}
              accessibilityRole="button"
              accessibilityLabel={`Open repurpose job ${repurposeJobTitle(job)}`}
            >
              <View style={styles.jobBody}>
                <Text style={styles.jobTitle} numberOfLines={1}>
                  {repurposeJobTitle(job)}
                </Text>
                <Text style={styles.jobMeta}>
                  {job.clip_count} clip{job.clip_count === 1 ? "" : "s"}
                  {formatJobDate(job.created_at)
                    ? ` · ${formatJobDate(job.created_at)}`
                    : ""}
                </Text>
                {job.error ? (
                  <Text style={styles.jobError} numberOfLines={1}>
                    {job.error}
                  </Text>
                ) : null}
              </View>
              <StatusPill label={job.status} color={statusColor(job.status)} />
            </Pressable>
          ))}
        </>
      ) : null}

      {clipJobs.length > 0 ? (
        <>
          <Text style={styles.sectionTitle}>Auto-clip jobs</Text>
          {clipJobs.map((job) => (
            <Pressable
              key={job.id}
              style={styles.jobRow}
              onPress={() => router.push(`/repurpose/clipping/clip/${job.id}`)}
              accessibilityRole="button"
              accessibilityLabel={`Open auto-clip job ${job.id}`}
            >
              <View style={styles.jobBody}>
                <Text style={styles.jobTitle} numberOfLines={1}>
                  {job.clip_count} short{job.clip_count === 1 ? "" : "s"} ·{" "}
                  {job.progress}%
                </Text>
                <Text style={styles.jobMeta}>
                  target {job.target_count} · {job.language}
                </Text>
                {job.error ? (
                  <Text style={styles.jobError} numberOfLines={1}>
                    {job.error}
                  </Text>
                ) : null}
              </View>
              <StatusPill label={job.state} color={statusColor(job.state)} />
            </Pressable>
          ))}
        </>
      ) : null}

      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.lg, gap: spacing.sm },
  center: { alignItems: "center", justifyContent: "center", flex: 1 },
  intro: {
    color: colors.textSecondary,
    fontSize: typeScale.caption,
    lineHeight: 20,
    marginBottom: spacing.sm,
  },
  segment: {
    flexDirection: "row",
    backgroundColor: colors.surfaceMuted,
    borderRadius: radius.md,
    padding: 3,
    gap: 3,
  },
  segmentBtn: {
    flex: 1,
    paddingVertical: spacing.sm,
    borderRadius: radius.sm,
    alignItems: "center",
  },
  segmentActive: { backgroundColor: colors.accent },
  segmentText: {
    color: colors.textSecondary,
    fontSize: typeScale.caption,
    fontWeight: weight.semibold,
  },
  segmentTextActive: { color: colors.onAccent, fontWeight: weight.bold },
  engineHint: {
    color: colors.textFaint,
    fontSize: typeScale.micro,
    lineHeight: 16,
    marginBottom: spacing.sm,
  },
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
  detectHint: {
    color: colors.textFaint,
    fontSize: typeScale.micro,
    marginTop: spacing.xs,
  },
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
  ingestLink: { alignSelf: "flex-start", paddingVertical: spacing.sm },
  ingestLinkText: {
    color: colors.accent,
    fontSize: typeScale.caption,
    fontWeight: weight.bold,
  },
  divider: {
    height: 1,
    backgroundColor: colors.border,
    marginVertical: spacing.md,
  },
  sectionTitle: {
    color: colors.textPrimary,
    fontSize: typeScale.subheading,
    fontWeight: weight.bold,
    marginTop: spacing.sm,
    marginBottom: spacing.xs,
  },
  jobRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.md,
  },
  jobBody: { flex: 1, gap: 2 },
  jobTitle: {
    color: colors.textPrimary,
    fontSize: typeScale.body,
    fontWeight: weight.semibold,
  },
  jobMeta: { color: colors.textFaint, fontSize: typeScale.micro },
  jobError: { color: colors.danger, fontSize: typeScale.micro },
  empty: {
    color: colors.textFaint,
    fontSize: typeScale.body,
    textAlign: "center",
    lineHeight: 22,
    paddingVertical: spacing.xl,
  },
  errorBox: { gap: spacing.sm, marginBottom: spacing.sm },
  error: { color: colors.danger, fontSize: typeScale.caption, lineHeight: 18 },
  retryBtn: {
    alignSelf: "flex-start",
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  retryText: {
    color: colors.textPrimary,
    fontSize: typeScale.caption,
    fontWeight: weight.semibold,
  },
  spacer: { height: 48 },
});
