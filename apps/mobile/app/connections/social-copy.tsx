/**
 * AI Social Copy — generate an optimized post title, caption and hashtags for a
 * FINISHED reel, tailored to a target platform. The copy is written server-side
 * from the job's own subject/script (never from client input); creators copy the
 * result to paste when posting manually.
 *
 * Pipeline:
 *   GET  /jobs                     → completed reels to pick from
 *   GET  /catalog/social-platforms → the platforms the generator supports
 *   POST /jobs/{id}/social         → title + caption + hashtags
 *
 * NAV MANIFEST (for the integration agent):
 *   { route: "/connections/social-copy", title: "AI Social Copy" }
 *
 * Accepts an optional deep-link param `?jobId=` to preselect a reel.
 */

import * as React from "react";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { generateSocial, listJobs, listSocialPlatforms } from "@/lib/api";
import { JobState } from "@/lib/types";
import type { Job, SocialMeta, SocialPlatform } from "@/lib/types";

import { jobShortLabel } from "@/components/connections/format";
import { CopyableField } from "@/components/social/CopyableField";
import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import { useSession } from "@/src/shared/auth";

/** A one-line, human label for a finished reel in the picker. */
function reelLabel(job: Job): string {
  const hook = String(job.hook ?? "").trim();
  if (hook) return hook.length > 48 ? `${hook.slice(0, 47)}…` : hook;
  return jobShortLabel(job.job_id);
}

interface LoadState {
  jobs: Job[];
  platforms: SocialPlatform[];
}

export default function SocialCopyScreen(): React.ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();
  const params = useLocalSearchParams<{ jobId?: string }>();

  const [loading, setLoading] = React.useState(true);
  const [loadError, setLoadError] = React.useState("");
  const [jobs, setJobs] = React.useState<Job[]>([]);
  const [platforms, setPlatforms] = React.useState<SocialPlatform[]>([]);

  const [jobId, setJobId] = React.useState<string | null>(null);
  const [platform, setPlatform] = React.useState<string | null>(null);
  const [language, setLanguage] = React.useState("");

  const [generating, setGenerating] = React.useState(false);
  const [genError, setGenError] = React.useState("");
  const [meta, setMeta] = React.useState<SocialMeta | null>(null);

  const load = React.useCallback(async (): Promise<LoadState> => {
    const [allJobs, plats] = await Promise.all([
      listJobs({ token }),
      listSocialPlatforms({ token }),
    ]);
    return {
      jobs: allJobs.filter((j) => j.state === JobState.Complete),
      platforms: plats,
    };
  }, [token]);

  const runLoad = React.useCallback(async () => {
    setLoading(true);
    setLoadError("");
    try {
      const next = await load();
      setJobs(next.jobs);
      setPlatforms(next.platforms);
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
      setPlatform((current) => {
        if (current && next.platforms.some((p) => String(p.id) === current)) {
          return current;
        }
        return next.platforms[0] ? String(next.platforms[0].id) : null;
      });
    } catch (err) {
      setLoadError(describeError(err, "Failed to load your reels."));
    } finally {
      setLoading(false);
    }
  }, [load, params.jobId]);

  React.useEffect(() => {
    void runLoad();
  }, [runLoad]);

  const onGenerate = React.useCallback(async () => {
    if (!jobId || !platform) return;
    setGenerating(true);
    setGenError("");
    setMeta(null);
    try {
      const trimmedLang = language.trim();
      const res = await generateSocial(
        jobId,
        {
          platform,
          ...(trimmedLang ? { language: trimmedLang } : {}),
        },
        { token },
      );
      setMeta(res);
    } catch (err) {
      setGenError(describeError(err, "Failed to generate social copy."));
    } finally {
      setGenerating(false);
    }
  }, [jobId, platform, language, token]);

  const canGenerate = !!jobId && !!platform && !generating;
  const hashtagsDisplay = meta?.hashtags?.length
    ? meta.hashtags.join(" ")
    : "";

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Stack.Screen options={{ title: "AI Social Copy" }} />

      <Text style={styles.intro}>
        Generate a ready-to-paste title, caption and hashtags for a finished
        reel, tailored to the platform you're posting on.
      </Text>

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.accent} />
          <Text style={styles.muted}>Loading your reels…</Text>
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
            Finish rendering a reel and it will show up here to write copy for.
          </Text>
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

          <Text style={styles.fieldLabel}>PLATFORM</Text>
          {platforms.length === 0 ? (
            <Text style={styles.muted}>
              No platforms available right now — try again shortly.
            </Text>
          ) : (
            <View style={styles.chips}>
              {platforms.map((p) => {
                const id = String(p.id);
                const selected = id === platform;
                return (
                  <Pressable
                    key={id}
                    style={[styles.chip, selected && styles.chipOn]}
                    onPress={() => setPlatform(id)}
                    accessibilityRole="button"
                    accessibilityState={{ selected }}
                  >
                    <Text
                      style={[styles.chipText, selected && styles.chipTextOn]}
                    >
                      {p.name || id}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          )}

          <Text style={styles.fieldLabel}>LANGUAGE (OPTIONAL)</Text>
          <TextInput
            style={styles.input}
            value={language}
            onChangeText={setLanguage}
            placeholder="e.g. en, es, tr — leave blank for the reel's language"
            placeholderTextColor={colors.muted}
            autoCapitalize="none"
            autoCorrect={false}
            editable={!generating}
          />

          {genError ? <Text style={styles.error}>{genError}</Text> : null}

          <Pressable
            style={[styles.generate, !canGenerate && styles.generateDisabled]}
            onPress={() => void onGenerate()}
            disabled={!canGenerate}
            accessibilityRole="button"
            accessibilityLabel="Generate social copy"
            accessibilityState={{ disabled: !canGenerate }}
          >
            {generating ? (
              <ActivityIndicator color={colors.bg} size="small" />
            ) : (
              <Text style={styles.generateText}>
                {meta ? "Regenerate copy" : "Generate copy"}
              </Text>
            )}
          </Pressable>

          {meta ? (
            <View style={styles.result}>
              <CopyableField
                label="Title"
                value={meta.title ?? ""}
                emptyText="No title generated"
              />
              <CopyableField
                label="Caption"
                value={meta.caption ?? ""}
                emptyText="No caption generated"
              />
              <CopyableField
                label="Hashtags"
                value={hashtagsDisplay}
                emptyText="No hashtags generated"
              />
            </View>
          ) : null}
        </View>
      )}

      <Pressable
        style={styles.manageLink}
        onPress={() => router.push("/connections/publish")}
        accessibilityRole="link"
      >
        <Text style={styles.manageLinkText}>Publish a reel instead</Text>
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
  input: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    padding: 12,
    color: colors.textPrimary,
    fontSize: 14,
    backgroundColor: colors.card,
  },
  generate: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: "center",
    marginTop: 4,
  },
  generateDisabled: { opacity: 0.5 },
  generateText: { color: colors.bg, fontWeight: "700", fontSize: 15 },
  result: {
    gap: 10,
    marginTop: 8,
    borderTopColor: colors.border,
    borderTopWidth: 1,
    paddingTop: 12,
  },
  error: { color: colors.error, fontSize: 13 },
  manageLink: { alignSelf: "flex-start", paddingVertical: 10 },
  manageLinkText: { color: colors.accent, fontSize: 13, fontWeight: "600" },
  spacer: { height: 24 },
});
