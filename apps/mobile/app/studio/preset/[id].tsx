/**
 * Studio · Preset Shelf · Use
 *
 * Nav manifest: { route: "/studio/preset/[id]", title: "Preset" } — reached by
 * tapping a tile on /studio/preset, not separately nav-registered (mirrors
 * /studio/template/[slug], which is reached the same way).
 *
 * The one-tap flow this screen is the whole point of: resolve the tapped
 * preset + a typed topic (and, for presets that animate a photo, an uploaded
 * image) into the normal Create body (POST /presets/shelf/{id}/plan), price it
 * first (POST /jobs/quote or /jobs/quote/preset), then start the render
 * through the SAME create routes every other Menivor surface uses
 * (POST /jobs or /generation/broll/generate) — no new render pipeline, no new
 * billing path. Mirrors apps/web/src/features/presets-shelf/PresetUse.tsx.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { Stack, useLocalSearchParams, useRouter } from "expo-router";

import {
  formatSeconds,
  getRun,
  getTile,
  planPreset,
  quotePlan,
  recordRun,
  startPlan,
  type PresetQuote,
  type PresetRunView,
  type PresetTile,
} from "@/lib/presets-shelf";
import { useSession } from "@/src/shared/auth";

import { PresetImagePicker } from "@/components/presets/PresetImagePicker";
import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import { StudioScreen } from "@/components/studio/StudioScreen";

const RUN_POLL_MS = 5000;

type Phase = "input" | "priced" | "running" | "done";

function firstParam(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return value[0] ?? "";
  return value ?? "";
}

export default function StudioPresetUseScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();
  const params = useLocalSearchParams<{ id?: string | string[] }>();
  const id = firstParam(params.id).trim();

  const openedAt = useRef(new Date().toISOString());
  const [tile, setTile] = useState<PresetTile | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");

  const [subject, setSubject] = useState("");
  const [imageKey, setImageKey] = useState("");
  const [phase, setPhase] = useState<Phase>("input");
  const [price, setPrice] = useState<PresetQuote | null>(null);
  const [jobId, setJobId] = useState("");
  const [run, setRun] = useState<PresetRunView | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");

  useEffect(() => {
    if (!id) {
      setStatus("error");
      setError("Missing preset id.");
      return;
    }
    let live = true;
    getTile(id, { token })
      .then((t) => {
        if (!live) return;
        setTile(t);
        setStatus("ready");
      })
      .catch((err) => {
        if (!live) return;
        setError(describeError(err, "This preset is not available."));
        setStatus("error");
      });
    return () => {
      live = false;
    };
  }, [id, token]);

  useEffect(() => {
    if (phase !== "running" || !jobId) return;
    let live = true;
    const tick = async () => {
      try {
        const view = await getRun(jobId, { token });
        if (!live) return;
        setRun(view);
        if (view.seconds_to_result !== null) setPhase("done");
      } catch {
        // keep polling; the task-queue link below always works
      }
    };
    void tick();
    const timer = setInterval(tick, RUN_POLL_MS);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [jobId, phase, token]);

  const needsImage = Boolean(tile?.inputs.includes("image")) && !imageKey;

  const planBody = useCallback(
    () => ({
      subject,
      ...(imageKey ? { image_key: imageKey } : {}),
    }),
    [subject, imageKey],
  );

  const onPrice = useCallback(async () => {
    if (!tile || !subject.trim()) return;
    setBusy(true);
    setActionError("");
    try {
      const resolved = await planPreset(tile.id, planBody(), { token });
      const quote = await quotePlan(tile, resolved, { token });
      setPrice(quote);
      setPhase("priced");
    } catch (err) {
      setActionError(describeError(err, "We could not price this preset."));
    } finally {
      setBusy(false);
    }
  }, [tile, subject, planBody, token]);

  const onMake = useCallback(async () => {
    if (!tile) return;
    setBusy(true);
    setActionError("");
    try {
      const resolved = await planPreset(tile.id, planBody(), { token });
      const idempotencyKey = `${Date.now()}-${tile.id}`;
      const id2 = await startPlan(resolved, { token, idempotencyKey });
      setJobId(id2);
      await recordRun(tile.id, { job_id: id2, opened_at: openedAt.current }, { token }).catch(() => undefined);
      setPhase("running");
    } catch (err) {
      setActionError(describeError(err, "We could not start this preset."));
    } finally {
      setBusy(false);
    }
  }, [tile, planBody, token]);

  const unit = useMemo(
    () => (tile?.credit_kind === "ai_video" ? "AI-video credit" : "credit"),
    [tile],
  );

  return (
    <StudioScreen
      status={status}
      error={error}
      onRetry={() => router.back()}
      loadingLabel="Loading preset…"
    >
      {tile ? (
        <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
          <Stack.Screen options={{ title: tile.name }} />
          <Image
            source={{ uri: tile.preview.poster_url }}
            style={styles.poster}
            resizeMode="cover"
            accessibilityLabel={`${tile.name} preview`}
          />
          <Text style={styles.name}>{tile.name}</Text>
          <Text style={styles.blurb}>{tile.blurb}</Text>

          {phase === "input" ? (
            <View style={styles.form}>
              <Text style={styles.label}>Your topic or link</Text>
              <TextInput
                style={styles.input}
                value={subject}
                onChangeText={setSubject}
                placeholder="A new espresso bar on our street"
                placeholderTextColor={colors.muted}
                maxLength={600}
                multiline
              />
              {tile.inputs.includes("image") ? (
                <PresetImagePicker
                  token={token}
                  disabled={busy}
                  onUploaded={(key) => setImageKey(key)}
                />
              ) : null}
              <Pressable
                style={[
                  styles.primary,
                  (busy || !subject.trim() || needsImage) && styles.primaryDisabled,
                ]}
                onPress={() => void onPrice()}
                disabled={busy || !subject.trim() || needsImage}
                accessibilityRole="button"
              >
                {busy ? (
                  <ActivityIndicator color={colors.bg} />
                ) : (
                  <Text style={styles.primaryText}>See the price</Text>
                )}
              </Pressable>
            </View>
          ) : phase === "priced" && price ? (
            <View style={styles.form}>
              <Text style={styles.priceText}>
                Uses {price.credits} {price.credits === 1 ? unit : `${unit}s`}.
              </Text>
              {price.affordable ? (
                <Pressable
                  style={[styles.primary, busy && styles.primaryDisabled]}
                  onPress={() => void onMake()}
                  disabled={busy}
                  accessibilityRole="button"
                >
                  {busy ? (
                    <ActivityIndicator color={colors.bg} />
                  ) : (
                    <Text style={styles.primaryText}>Make it</Text>
                  )}
                </Pressable>
              ) : (
                <Pressable
                  style={styles.primary}
                  onPress={() => router.push("/wallet")}
                  accessibilityRole="button"
                >
                  <Text style={styles.primaryText}>Top up to make it</Text>
                </Pressable>
              )}
              <Pressable
                style={styles.secondary}
                onPress={() => setPhase("input")}
                disabled={busy}
                accessibilityRole="button"
              >
                <Text style={styles.secondaryText}>Change the topic</Text>
              </Pressable>
            </View>
          ) : (
            <View style={styles.form}>
              {run?.seconds_to_result !== null && run?.seconds_to_result !== undefined ? (
                <Text style={styles.priceText}>
                  First result in {formatSeconds(run.seconds_to_result)} (target{" "}
                  {formatSeconds(run.target_seconds)}).
                </Text>
              ) : (
                <Text style={styles.priceText}>
                  Rendering. The clock started when you tapped Make it.
                </Text>
              )}
              <Pressable
                style={styles.primary}
                onPress={() => router.push(`/jobs/reels/tasks/${encodeURIComponent(jobId)}`)}
                accessibilityRole="button"
              >
                <Text style={styles.primaryText}>Open the result</Text>
              </Pressable>
            </View>
          )}

          {actionError ? <Text style={styles.error}>{actionError}</Text> : null}
        </ScrollView>
      ) : null}
    </StudioScreen>
  );
}

const styles = StyleSheet.create({
  container: { padding: 16, gap: 12, paddingBottom: 48 },
  poster: {
    width: "100%",
    aspectRatio: 9 / 16,
    borderRadius: 16,
    backgroundColor: colors.card,
  },
  name: { color: colors.textPrimary, fontSize: 20, fontWeight: "700" },
  blurb: { color: colors.textSecondary, fontSize: 14, lineHeight: 20 },
  form: { gap: 12, marginTop: 8 },
  label: { color: colors.textPrimary, fontSize: 13, fontWeight: "600" },
  input: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    color: colors.textPrimary,
    fontSize: 15,
    minHeight: 48,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  primary: {
    backgroundColor: colors.accent,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
  },
  primaryDisabled: { opacity: 0.5 },
  primaryText: { color: colors.bg, fontSize: 15, fontWeight: "700" },
  secondary: { alignItems: "center", paddingVertical: 10 },
  secondaryText: { color: colors.textSecondary, fontWeight: "600" },
  priceText: { color: colors.textPrimary, fontSize: 15 },
  error: { color: colors.error, fontSize: 13 },
});
