/**
 * Publish a Reel — post a FINISHED, owned reel straight to a connected
 * platform's native API (TikTok / Instagram / YouTube). Pick one of your
 * completed reels, choose a target you've connected, optionally auto-write the
 * caption with AI, then publish.
 *
 * Pipeline:
 *   GET  /jobs                       → completed reels to choose from
 *   GET  /me/connections             → which providers are live targets
 *   GET  /publishing/native/platforms→ which providers accept a native publish
 *   POST /jobs/{id}/social           → optional AI title/caption/hashtags
 *   POST /jobs/{id}/publish/native   → the actual publish (Idempotency-Key set)
 *
 * NAV MANIFEST (for the integration agent):
 *   { route: "/connections/publish", title: "Publish a Reel" }
 *
 * Accepts optional deep-link params `?jobId=&provider=` to preselect a reel and
 * target (used by the reel detail + connections screens). Pro-gated (publishing).
 */

import * as React from "react";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import * as Linking from "expo-linking";
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

import { generateSocial, getConnections, listJobs } from "@/lib/api";
import {
  listNativePlatforms,
  publishNative,
  type NativePublishResult,
} from "@/lib/publishing";
import { JobState } from "@/lib/types";
import type { Connection, Job, SocialPlatformId } from "@/lib/types";

import { jobShortLabel, providerLabel } from "@/components/connections/format";
import { CopyableField } from "@/components/social/CopyableField";
import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import { useSession } from "@/src/shared/auth";
import { ProExportAccess, useRevenueCat } from "@/src/shared/billing";
import { LaunchStatusBanner } from "@/components/launch/LaunchStatusBanner";
import { useLaunchStatus } from "@/src/shared/hooks";

/** A provider id → the social-copy platform id the AI generator understands. */
function toSocialPlatform(provider: string): SocialPlatformId | string {
  return provider === "youtube" ? "youtube_shorts" : provider;
}

/** Fresh, per-attempt idempotency key so a transport retry never double-posts. */
function newIdempotencyKey(jobId: string, provider: string): string {
  return `publish:${jobId}:${provider}:${Date.now()}:${Math.random()
    .toString(36)
    .slice(2, 10)}`;
}

/** A one-line, human label for a finished reel in the picker. */
function reelLabel(job: Job): string {
  const hook = String(job.hook ?? "").trim();
  if (hook) return hook.length > 48 ? `${hook.slice(0, 47)}…` : hook;
  return jobShortLabel(job.job_id);
}

interface LoadState {
  jobs: Job[];
  targets: string[];
}

export default function ConnectionsPublishScreen(): React.ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const launch = useLaunchStatus(token);
  const router = useRouter();
  const { requireProAccess } = useRevenueCat();
  const params = useLocalSearchParams<{ jobId?: string; provider?: string }>();

  const [loading, setLoading] = React.useState(true);
  const [loadError, setLoadError] = React.useState("");
  const [jobs, setJobs] = React.useState<Job[]>([]);
  const [targets, setTargets] = React.useState<string[]>([]);

  const [jobId, setJobId] = React.useState<string | null>(null);
  const [provider, setProvider] = React.useState<string | null>(null);
  const [title, setTitle] = React.useState("");
  const [caption, setCaption] = React.useState("");
  const [hashtags, setHashtags] = React.useState<string[]>([]);

  const [generating, setGenerating] = React.useState(false);
  const [publishing, setPublishing] = React.useState(false);
  const [genError, setGenError] = React.useState("");
  const [publishError, setPublishError] = React.useState("");
  const [result, setResult] = React.useState<NativePublishResult | null>(null);

  const load = React.useCallback(async (): Promise<LoadState> => {
    const [allJobs, connections, native] = await Promise.all([
      listJobs({ token }),
      getConnections({ token }),
      listNativePlatforms({ token }),
    ]);
    const completed = allJobs.filter((j) => j.state === JobState.Complete);
    const connected = new Set(
      connections
        .filter((c: Connection) => String(c.status).toLowerCase() !== "expired")
        .map((c: Connection) => String(c.provider)),
    );
    const availableTargets = native.platforms.filter((p) => connected.has(p));
    return { jobs: completed, targets: availableTargets };
  }, [token]);

  const runLoad = React.useCallback(async () => {
    setLoading(true);
    setLoadError("");
    try {
      const next = await load();
      setJobs(next.jobs);
      setTargets(next.targets);
      // Honour deep-link preselection when valid, else default sensibly.
      setJobId((current) => {
        const preferred = String(params.jobId ?? "");
        if (preferred && next.jobs.some((j) => j.job_id === preferred)) {
          return preferred;
        }
        if (current && next.jobs.some((j) => j.job_id === current)) {
          return current;
        }
        return next.jobs[0]?.job_id ?? null;
      });
      setProvider((current) => {
        const preferred = String(params.provider ?? "");
        if (preferred && next.targets.includes(preferred)) return preferred;
        if (current && next.targets.includes(current)) return current;
        return next.targets[0] ?? null;
      });
    } catch (err) {
      setLoadError(describeError(err, "Failed to load your reels and targets."));
    } finally {
      setLoading(false);
    }
  }, [load, params.jobId, params.provider]);

  React.useEffect(() => {
    void runLoad();
  }, [runLoad]);

  const onGenerate = React.useCallback(async () => {
    if (!jobId || !provider) return;
    setGenerating(true);
    setGenError("");
    try {
      const meta = await generateSocial(
        jobId,
        { platform: toSocialPlatform(provider) },
        { token },
      );
      setTitle(meta.title ?? "");
      setCaption(meta.caption ?? "");
      setHashtags(Array.isArray(meta.hashtags) ? meta.hashtags : []);
    } catch (err) {
      setGenError(describeError(err, "Failed to generate social copy."));
    } finally {
      setGenerating(false);
    }
  }, [jobId, provider, token]);

  const doPublish = React.useCallback(async () => {
    if (!jobId || !provider) return;
    setPublishing(true);
    setPublishError("");
    setResult(null);
    try {
      const access = await requireProAccess();
      if (!access.allowed) {
        setPublishError(access.snapshot.message);
        return;
      }
      const res = await publishNative(
        jobId,
        {
          platform: provider,
          title: title.trim() || undefined,
          caption: caption.trim() || undefined,
          hashtags: hashtags.length > 0 ? hashtags : undefined,
        },
        { token, idempotencyKey: newIdempotencyKey(jobId, provider) },
      );
      setResult(res);
    } catch (err) {
      setPublishError(describeError(err, "Failed to publish the reel."));
    } finally {
      setPublishing(false);
    }
  }, [jobId, provider, title, caption, hashtags, token, requireProAccess]);

  const confirmPublish = React.useCallback(() => {
    if (!jobId || !provider) return;
    Alert.alert(
      `Publish to ${providerLabel(provider)}?`,
      "This posts your reel to the connected account right now.",
      [
        { text: "Cancel", style: "cancel" },
        { text: "Publish", onPress: () => void doPublish() },
      ],
      { cancelable: true },
    );
  }, [jobId, provider, doPublish]);

  const onOpenResult = React.useCallback((url: string) => {
    if (url) void Linking.openURL(url);
  }, []);

  const canPublish = !!jobId && !!provider && !publishing;

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <LaunchStatusBanner status={launch.status} gate="publishing" />
      <Stack.Screen options={{ title: "Publish a Reel" }} />

      <Text style={styles.intro}>
        Post a finished reel straight to a connected account. Auto-write the
        caption with AI, tweak it, then publish.
      </Text>

      <ProExportAccess feature="publishing" />

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.accent} />
          <Text style={styles.muted}>Loading your reels and targets…</Text>
        </View>
      ) : loadError ? (
        <View style={styles.errorBox}>
          <Text style={styles.errorText}>{loadError}</Text>
          <Pressable style={styles.retry} onPress={() => void runLoad()}>
            <Text style={styles.retryText}>Try again</Text>
          </Pressable>
        </View>
      ) : jobs.length === 0 ? (
        <View style={styles.emptyBox}>
          <Text style={styles.emptyTitle}>No finished reels yet</Text>
          <Text style={styles.muted}>
            Once a reel finishes rendering it will show up here to publish.
          </Text>
        </View>
      ) : targets.length === 0 ? (
        <View style={styles.emptyBox}>
          <Text style={styles.emptyTitle}>No connected targets</Text>
          <Text style={styles.muted}>
            Connect a TikTok, Instagram or YouTube account to publish to it.
          </Text>
          <Pressable
            style={styles.primaryLink}
            onPress={() => router.push("/connections/manage")}
          >
            <Text style={styles.primaryLinkText}>Manage connections</Text>
          </Pressable>
        </View>
      ) : (
        <View style={styles.form}>
          <Text style={styles.fieldLabel}>REEL</Text>
          <View style={styles.chips}>
            {jobs.map((job) => {
              const selected = job.job_id === jobId;
              return (
                <Pressable
                  key={job.job_id}
                  style={[styles.chip, selected && styles.chipOn]}
                  onPress={() => setJobId(job.job_id)}
                  accessibilityRole="button"
                  accessibilityState={{ selected }}
                >
                  <Text
                    style={[styles.chipText, selected && styles.chipTextOn]}
                    numberOfLines={1}
                  >
                    {reelLabel(job)}
                  </Text>
                </Pressable>
              );
            })}
          </View>

          <Text style={styles.fieldLabel}>PUBLISH TO</Text>
          <View style={styles.chips}>
            {targets.map((p) => {
              const selected = p === provider;
              return (
                <Pressable
                  key={p}
                  style={[styles.chip, selected && styles.chipOn]}
                  onPress={() => setProvider(p)}
                  accessibilityRole="button"
                  accessibilityState={{ selected }}
                >
                  <Text style={[styles.chipText, selected && styles.chipTextOn]}>
                    {providerLabel(p)}
                  </Text>
                </Pressable>
              );
            })}
          </View>

          <View style={styles.copyHeader}>
            <Text style={styles.fieldLabel}>CAPTION</Text>
            <Pressable
              style={[styles.aiBtn, generating && styles.aiBtnBusy]}
              onPress={() => void onGenerate()}
              disabled={generating || !jobId || !provider}
              accessibilityRole="button"
              accessibilityLabel="Generate caption with AI"
            >
              {generating ? (
                <ActivityIndicator color={colors.accent} size="small" />
              ) : (
                <Text style={styles.aiBtnText}>Write with AI</Text>
              )}
            </Pressable>
          </View>
          {genError ? <Text style={styles.error}>{genError}</Text> : null}

          <TextInput
            style={styles.input}
            value={title}
            onChangeText={setTitle}
            placeholder="Title (optional)"
            placeholderTextColor={colors.muted}
            editable={!publishing}
          />
          <TextInput
            style={[styles.input, styles.multiline]}
            value={caption}
            onChangeText={setCaption}
            placeholder="Write a caption for this post…"
            placeholderTextColor={colors.muted}
            multiline
            editable={!publishing}
          />
          {hashtags.length > 0 ? (
            <Text style={styles.hashtags}>{hashtags.join(" ")}</Text>
          ) : null}

          {publishError ? (
            <Text style={styles.error}>{publishError}</Text>
          ) : null}

          <Pressable
            style={[styles.publish, !canPublish && styles.publishDisabled]}
            onPress={confirmPublish}
            disabled={!canPublish}
            accessibilityRole="button"
            accessibilityLabel="Publish reel"
            accessibilityState={{ disabled: !canPublish }}
          >
            {publishing ? (
              <ActivityIndicator color={colors.bg} size="small" />
            ) : (
              <Text style={styles.publishText}>
                Publish to {provider ? providerLabel(provider) : "…"}
              </Text>
            )}
          </Pressable>

          {result ? (
            <View style={styles.result}>
              <Text style={styles.resultTitle}>
                Published to {providerLabel(result.platform)} ·{" "}
                {result.status || "done"}
              </Text>
              <CopyableField
                label="Post URL"
                value={result.url ?? ""}
                emptyText="No URL returned"
              />
              {result.url ? (
                <Pressable
                  style={styles.openBtn}
                  onPress={() => onOpenResult(result.url)}
                >
                  <Text style={styles.openBtnText}>Open post</Text>
                </Pressable>
              ) : null}
              {result.external_id ? (
                <Text style={styles.muted} numberOfLines={1}>
                  Post id: {result.external_id}
                </Text>
              ) : null}
            </View>
          ) : null}
        </View>
      )}

      <Pressable
        style={styles.manageLink}
        onPress={() => router.push("/connections/manage")}
        accessibilityRole="link"
      >
        <Text style={styles.manageLinkText}>Manage connected accounts</Text>
      </Pressable>
      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16, gap: 12 },
  intro: { color: colors.textSecondary, fontSize: 14, lineHeight: 20 },
  center: { alignItems: "center", justifyContent: "center", paddingVertical: 28, gap: 8 },
  muted: { color: colors.muted, fontSize: 13, lineHeight: 18 },
  errorBox: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 12,
    alignItems: "flex-start",
  },
  errorText: { color: colors.error, fontSize: 14 },
  retry: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  retryText: { color: colors.textSecondary, fontWeight: "600" },
  emptyBox: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 18,
    gap: 8,
  },
  emptyTitle: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  primaryLink: { marginTop: 4 },
  primaryLinkText: { color: colors.accent, fontWeight: "700", fontSize: 14 },
  form: { gap: 10 },
  fieldLabel: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 0.5,
    marginTop: 4,
  },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 7,
    backgroundColor: colors.card,
    maxWidth: "100%",
  },
  chipOn: { borderColor: colors.primary, backgroundColor: colors.cardAlt },
  chipText: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  chipTextOn: { color: colors.accent },
  copyHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: 4,
  },
  aiBtn: {
    borderColor: colors.accent,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 6,
    minWidth: 96,
    alignItems: "center",
  },
  aiBtnBusy: { opacity: 0.7 },
  aiBtnText: { color: colors.accent, fontWeight: "700", fontSize: 12 },
  input: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    padding: 12,
    color: colors.textPrimary,
    fontSize: 14,
    backgroundColor: colors.card,
  },
  multiline: { minHeight: 96, textAlignVertical: "top" },
  hashtags: { color: colors.accent, fontSize: 13, lineHeight: 19 },
  publish: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: "center",
    marginTop: 4,
  },
  publishDisabled: { opacity: 0.5 },
  publishText: { color: colors.bg, fontWeight: "700", fontSize: 15 },
  result: {
    gap: 8,
    marginTop: 8,
    borderTopColor: colors.border,
    borderTopWidth: 1,
    paddingTop: 12,
  },
  resultTitle: { color: colors.success, fontSize: 14, fontWeight: "700" },
  openBtn: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
  },
  openBtnText: { color: colors.accent, fontWeight: "700", fontSize: 14 },
  error: { color: colors.error, fontSize: 13 },
  manageLink: { alignSelf: "flex-start", paddingVertical: 10 },
  manageLinkText: { color: colors.accent, fontSize: 13, fontWeight: "600" },
  spacer: { height: 24 },
});
