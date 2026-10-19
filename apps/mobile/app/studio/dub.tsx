/**
 * Route: /studio/dub — standalone Dub Studio. Dub ANY video (not only a
 * finished reel): upload one from the phone or pick one already uploaded,
 * choose the spoken language and the language to dub into, pick a voice
 * engine (free voices by default), and get the dubbed video plus subtitle
 * files. Running dubs are polled until they finish.
 *
 * Backed by GET /dub/options, POST /dub/videos, GET /dub/videos and
 * GET /dub/videos/{id} — the same domain as the web's /studio/dub.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Linking,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { Stack, useFocusEffect } from "expo-router";

import { presignAndUpload, type LocalFile } from "@/lib/api";
import { listUploads, uploadMediaKind, type UploadItem } from "@/lib/uploads";
import {
  buildDubRequest,
  createDubVideo,
  defaultEngine,
  dubCost,
  getDubOptions,
  getDubVideo,
  isTerminalDub,
  languageLabel,
  listDubVideos,
  upsertDub,
  type DubOptions,
  type DubVideo,
  type DubVoiceEngine,
} from "@/lib/dub-studio";
import { readableApiMessage } from "@/lib/social-inbox";
import { ApiError, POLL_INTERVAL_MS } from "@/src/shared/api";
import { useSession } from "@/src/shared/auth";
import { JobVideo, pickRecordingFromFiles, pickRecordingFromLibrary } from "@/src/shared/media";
import { colors, radius, spacing, typeScale } from "@/src/shared/theme";
import { Button, Chip, EmptyState, ErrorState } from "@/components/ui";

function describe(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 402) return "Not enough credits for this dub. Free voices cost less.";
    if (err.status === 413) return "That video is too large to dub.";
    if (err.status === 429) return "Too many dubs at once. Wait a minute and try again.";
    if (err.status === 503) return "Dubbing is unavailable right now.";
    return readableApiMessage(err.message, fallback);
  }
  return err instanceof Error ? err.message : fallback;
}

function stateLabel(dub: DubVideo): string {
  if (dub.state === "complete") return "Ready";
  if (dub.state === "failed") return dub.refunded ? "Failed · refunded" : "Failed";
  return `Dubbing ${Math.max(0, Math.min(100, Math.round(dub.progress)))}%`;
}

export default function DubStudioScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const [options, setOptions] = useState<DubOptions | null>(null);
  const [videos, setVideos] = useState<UploadItem[]>([]);
  const [history, setHistory] = useState<DubVideo[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [videoKey, setVideoKey] = useState("");
  const [videoName, setVideoName] = useState("");
  const [sourceLanguage, setSourceLanguage] = useState("en");
  const [targetLanguage, setTargetLanguage] = useState("");
  const [engine, setEngine] = useState<DubVoiceEngine["id"] | "">("");
  const [voice, setVoice] = useState("");
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [openDub, setOpenDub] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const [opts, dubs, uploads] = await Promise.all([
        getDubOptions({ token }),
        listDubVideos(20, { token }).catch(() => [] as DubVideo[]),
        listUploads({ token }).catch(() => [] as UploadItem[]),
      ]);
      setOptions(opts);
      setHistory(dubs);
      setVideos(uploads.filter((u) => uploadMediaKind(u) === "video" && u.key));
      setEngine((prev) => prev || defaultEngine(opts.voice_engines));
    } catch (err) {
      setLoadError(describe(err, "Could not load Dub Studio."));
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

  // Poll dubs that are still processing.
  const pending = useMemo(() => history.filter((d) => !isTerminalDub(d)).map((d) => d.dub_id), [history]);
  const pendingKey = pending.join(",");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    if (!pendingKey) return undefined;
    const ids = pendingKey.split(",");
    pollRef.current = setInterval(() => {
      ids.forEach((dubId) => {
        getDubVideo(dubId, { token })
          .then((dub) => setHistory((prev) => upsertDub(prev, dub)))
          .catch(() => undefined);
      });
    }, POLL_INTERVAL_MS);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [pendingKey, token]);

  const languages = options?.languages ?? [];
  const targetVoices = useMemo(
    () => languages.find((l) => l.code === targetLanguage)?.voices ?? [],
    [languages, targetLanguage],
  );
  const cost = options && engine ? dubCost(options, engine) : 0;

  const upload = useCallback(
    async (pick: () => Promise<LocalFile | null>) => {
      setFormError(null);
      let file: LocalFile | null;
      try {
        file = await pick();
      } catch (err) {
        setFormError(describe(err, "Could not open your videos."));
        return;
      }
      if (!file) return;
      if (options && options.max_bytes > 0 && file.size > options.max_bytes) {
        setFormError(`That video is over the ${Math.round(options.max_bytes / 1_000_000)} MB limit.`);
        return;
      }
      setVideoName(file.name);
      setUploadProgress(0);
      try {
        const result = await presignAndUpload(file, {
          token,
          onProgress: (f) => setUploadProgress(Math.round(f * 100)),
        });
        setVideoKey(result.key);
        setUploadProgress(null);
      } catch (err) {
        setUploadProgress(null);
        setVideoName("");
        setFormError(describe(err, "Upload failed. Check your connection and try again."));
      }
    },
    [options, token],
  );

  const onSubmit = useCallback(async () => {
    if (!options) return;
    const built = buildDubRequest(
      { videoKey, sourceLanguage, targetLanguage, engine, voice },
      options,
    );
    if (!built.ok) {
      setFormError(built.error);
      return;
    }
    setSubmitting(true);
    setFormError(null);
    try {
      const dub = await createDubVideo(built.body, { token });
      setHistory((prev) => upsertDub(prev, dub));
      setOpenDub(dub.dub_id);
    } catch (err) {
      setFormError(describe(err, "Could not start the dub."));
    } finally {
      setSubmitting(false);
    }
  }, [engine, options, sourceLanguage, targetLanguage, token, videoKey, voice]);

  const openUrl = useCallback(async (url: string) => {
    try {
      await Linking.openURL(url);
    } catch {
      setFormError("Could not open that file.");
    }
  }, []);

  if (loading && !options) {
    return (
      <View style={styles.center}>
        <Stack.Screen options={{ title: "Dub a video" }} />
        <ActivityIndicator color={colors.accent} />
      </View>
    );
  }

  if (!options) {
    return (
      <View style={styles.center}>
        <Stack.Screen options={{ title: "Dub a video" }} />
        <ErrorState message={loadError ?? "Could not load Dub Studio."} onRetry={load} />
      </View>
    );
  }

  return (
    <ScrollView
      style={styles.flex}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />}
    >
      <Stack.Screen options={{ title: "Dub a video" }} />
      <Text style={styles.lead}>
        Upload a video, pick the language to dub into, and get the dubbed video plus subtitle files. Free voices
        are the default.
      </Text>
      {!options.available ? (
        <Text style={styles.warn}>Dubbing is not set up on this server yet. You can still browse past dubs.</Text>
      ) : null}

      <Text style={styles.section}>1. Video</Text>
      <View style={styles.row}>
        <Button
          label="From Photos"
          variant="secondary"
          size="sm"
          disabled={uploadProgress !== null || submitting}
          onPress={() => upload(pickRecordingFromLibrary)}
        />
        <Button
          label="From Files"
          variant="secondary"
          size="sm"
          disabled={uploadProgress !== null || submitting}
          onPress={() => upload(pickRecordingFromFiles)}
        />
      </View>
      {uploadProgress !== null ? (
        <Text style={styles.faint}>
          Uploading {videoName} · {uploadProgress}%
        </Text>
      ) : videoKey ? (
        <Text style={styles.picked} numberOfLines={1}>
          Selected: {videoName || videoKey.split("/").pop()}
        </Text>
      ) : null}
      {videos.length > 0 ? (
        <>
          <Text style={styles.faint}>Or pick a video you already uploaded</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
            {videos.slice(0, 20).map((v) => (
              <Chip
                key={v.id}
                label={v.filename}
                active={videoKey === v.key}
                onPress={() => {
                  setVideoKey(v.key);
                  setVideoName(v.filename);
                  setFormError(null);
                }}
              />
            ))}
          </ScrollView>
        </>
      ) : null}

      <Text style={styles.section}>2. Spoken language</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
        {languages.map((l) => (
          <Chip key={l.code} label={l.label} active={sourceLanguage === l.code} onPress={() => setSourceLanguage(l.code)} />
        ))}
      </ScrollView>

      <Text style={styles.section}>3. Dub into</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
        {languages
          .filter((l) => l.code !== sourceLanguage)
          .map((l) => (
            <Chip
              key={l.code}
              label={l.label}
              active={targetLanguage === l.code}
              onPress={() => {
                setTargetLanguage(l.code);
                setVoice("");
              }}
            />
          ))}
      </ScrollView>

      <Text style={styles.section}>4. Voice</Text>
      <View style={styles.wrap}>
        {options.voice_engines.map((e) => (
          <Chip
            key={e.id}
            label={e.available ? e.label : `${e.label} (not set up)`}
            active={engine === e.id}
            disabled={!e.available}
            onPress={() => {
              setEngine(e.id);
              setVoice("");
            }}
          />
        ))}
      </View>
      {engine === "edge" && targetVoices.length > 1 ? (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
          <Chip label="Default voice" active={voice === ""} onPress={() => setVoice("")} />
          {targetVoices.map((v) => (
            <Chip key={v} label={v} active={voice === v} onPress={() => setVoice(v)} />
          ))}
        </ScrollView>
      ) : null}

      {formError ? <Text style={styles.error}>{formError}</Text> : null}
      <Button
        label={
          targetLanguage
            ? `Dub into ${languageLabel(languages, targetLanguage)}${cost > 0 ? ` · ${cost} credit${cost === 1 ? "" : "s"}` : " · free"}`
            : "Dub video"
        }
        loading={submitting}
        disabled={submitting || uploadProgress !== null || !options.available}
        onPress={onSubmit}
      />
      {options.max_seconds > 0 ? (
        <Text style={styles.faint}>Videos up to {Math.round(options.max_seconds / 60)} minutes.</Text>
      ) : null}

      <Text style={styles.section}>Your dubs</Text>
      {history.length === 0 ? (
        <EmptyState title="No dubs yet" body="Dubbed videos and their subtitle files show up here." />
      ) : (
        history.map((dub) => {
          const open = openDub === dub.dub_id;
          return (
            <View key={dub.dub_id} style={styles.card}>
              <View style={styles.cardTop}>
                <Text style={styles.cardTitle}>
                  {languageLabel(languages, dub.source_language)} to {languageLabel(languages, dub.target_language)}
                </Text>
                <Text style={[styles.faint, dub.state === "failed" && styles.errorText]}>{stateLabel(dub)}</Text>
              </View>
              {dub.state === "failed" && dub.error ? <Text style={styles.errorText}>{dub.error}</Text> : null}
              {dub.state === "complete" && dub.video_url ? (
                <>
                  {open ? <JobVideo uri={dub.video_url} /> : null}
                  <View style={styles.row}>
                    <Button
                      label={open ? "Hide" : "Play"}
                      variant="secondary"
                      size="sm"
                      onPress={() => setOpenDub(open ? null : dub.dub_id)}
                    />
                    <Button label="Download video" variant="ghost" size="sm" onPress={() => openUrl(dub.video_url)} />
                  </View>
                  {dub.subtitles.length > 0 ? (
                    <View style={styles.wrap}>
                      {dub.subtitles.map((s) => (
                        <Chip
                          key={s.key}
                          label={`Subtitles · ${languageLabel(languages, s.language)}`}
                          onPress={() => openUrl(s.url)}
                        />
                      ))}
                    </View>
                  ) : null}
                </>
              ) : null}
              {!isTerminalDub(dub) ? <ActivityIndicator color={colors.accent} style={styles.spinner} /> : null}
            </View>
          );
        })
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bg },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.bg, padding: spacing.lg },
  content: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xxl },
  lead: { color: colors.textSecondary, fontSize: typeScale.caption, lineHeight: 19 },
  warn: { color: colors.accent, fontSize: typeScale.caption, lineHeight: 18 },
  section: { color: colors.textPrimary, fontSize: typeScale.subheading, fontWeight: "700", marginTop: spacing.sm },
  row: { flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" },
  wrap: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  chips: { gap: spacing.sm, paddingRight: spacing.lg },
  faint: { color: colors.textFaint, fontSize: typeScale.micro },
  picked: { color: colors.textPrimary, fontSize: typeScale.caption },
  error: { color: colors.danger, fontSize: typeScale.caption },
  errorText: { color: colors.danger, fontSize: typeScale.micro },
  card: {
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    padding: spacing.md,
    gap: spacing.sm,
  },
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: spacing.sm },
  cardTitle: { color: colors.textPrimary, fontSize: typeScale.body, fontWeight: "600", flexShrink: 1 },
  spinner: { alignSelf: "flex-start" },
});
