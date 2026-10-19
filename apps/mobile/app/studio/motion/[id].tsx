/**
 * Studio · Motion Preset Detail + Compile.
 *
 * Nav manifest: { route: "/studio/motion/[id]", title: "Motion Preset" }
 *
 * One camera-move preset's full detail (GET /motion/{id}) with its resolved
 * FFmpeg filter and/or model camera-control sub-specs. The creator picks the
 * reel to plan the move for (their finished jobs, GET /jobs), scrubs the
 * intensity (0..100), and compiles a deterministic plan (POST /motion/{id}/
 * compile) behind a confirmation dialog. The compiled MotionPlan is rendered
 * inline (class, filter graph, model camera pose / frame geometry / provider
 * hints), and a shortcut jumps to the compile history the call just recorded.
 *
 * The compile engine is DB-free and deterministic — the same preset + intensity
 * always yields the same plan — so this is safe to run repeatedly. Explicit
 * loading / error / not-found states; the job picker degrades gracefully when
 * the caller has no finished reels yet.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { Stack, useLocalSearchParams, useRouter } from "expo-router";

import { ApiError, listJobs } from "@/lib/api";
import {
  compileMotion,
  getMotion,
  MOTION_INTENSITY_MAX,
  MOTION_INTENSITY_MIN,
  type MotionDetail,
  type MotionPlan,
} from "@/lib/api/motion";
import { JobState, type Job } from "@/lib/types";
import { useSession } from "@/src/shared/auth";

import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import { StudioScreen } from "@/components/studio/StudioScreen";
import { Icon } from "@/components/ui/Icon";

const INTENSITY_STEP = 5;

function firstParam(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return value[0] ?? "";
  return value ?? "";
}

/** A short, stable label for a job id (last 6 chars, uppercased). */
function shortId(jobId: string): string {
  const tail = jobId.length > 6 ? jobId.slice(-6) : jobId;
  return tail.toUpperCase();
}

function clampIntensity(value: number): number {
  return Math.max(MOTION_INTENSITY_MIN, Math.min(MOTION_INTENSITY_MAX, value));
}

interface SpecRow {
  label: string;
  value: string;
}

export default function StudioMotionDetailScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();
  const params = useLocalSearchParams<{ id?: string | string[] }>();
  const presetId = firstParam(params.id).trim();

  const [detail, setDetail] = useState<MotionDetail | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [error, setError] = useState("");
  const [notFound, setNotFound] = useState(false);

  const [intensity, setIntensity] = useState(50);

  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);

  const [compiling, setCompiling] = useState(false);
  const [plan, setPlan] = useState<MotionPlan | null>(null);
  const [actionError, setActionError] = useState("");

  const load = useCallback(async () => {
    if (!presetId) {
      setNotFound(true);
      setStatus("error");
      setError("No motion preset was specified.");
      return;
    }
    setStatus("loading");
    setNotFound(false);
    try {
      const data = await getMotion(presetId, { token });
      setDetail(data);
      setIntensity(clampIntensity(data.intensity ?? 50));
      setStatus("ready");
      setError("");
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setNotFound(true);
      }
      setError(describeError(err, "Failed to load this motion preset."));
      setStatus("error");
    }
  }, [presetId, token]);

  useEffect(() => {
    void load();
  }, [load]);

  // Finished reels the move can be planned against (best-effort; a failure here
  // never blocks compiling — the plan is still deterministic without a job).
  useEffect(() => {
    let active = true;
    listJobs({ token })
      .then((all) => {
        if (!active) return;
        const done = all.filter((j) => j.state === JobState.Complete);
        setJobs(done);
        setSelectedJobId((prev) => prev ?? done[0]?.job_id ?? null);
      })
      .catch(() => {
        /* job picker simply stays empty */
      });
    return () => {
      active = false;
    };
  }, [token]);

  const adjust = useCallback((delta: number) => {
    setIntensity((v) => clampIntensity(v + delta));
  }, []);

  const runCompile = useCallback(async () => {
    if (!detail) return;
    setCompiling(true);
    setActionError("");
    try {
      const result = await compileMotion(detail.id, { intensity }, { token });
      setPlan(result);
    } catch (err) {
      setActionError(describeError(err, "Failed to compile this motion."));
    } finally {
      setCompiling(false);
    }
  }, [detail, intensity, token]);

  const confirmCompile = useCallback(() => {
    if (!detail) return;
    const target = selectedJobId
      ? `Reel ${shortId(selectedJobId)}`
      : "your next reel";
    Alert.alert(
      "Compile motion plan",
      `Compile "${detail.name}" at intensity ${intensity} for ${target}? ` +
        "This records the move in your compile history.",
      [
        { text: "Cancel", style: "cancel" },
        { text: "Compile", onPress: () => void runCompile() },
      ],
    );
  }, [detail, intensity, selectedJobId, runCompile]);

  const specRows = useMemo<SpecRow[]>(() => {
    if (!detail) return [];
    const rows: SpecRow[] = [
      { label: "Preset id", value: detail.id },
      { label: "Category", value: detail.category },
      { label: "Render class", value: detail.render_class },
      {
        label: "Provider",
        value: detail.requires_provider ? "Required" : "Not required",
      },
    ];
    if (detail.filter) {
      rows.push({ label: "FFmpeg move", value: detail.filter.camera_motion });
      if (detail.filter.effects.length > 0) {
        rows.push({ label: "Effects", value: detail.filter.effects.join(", ") });
      }
    }
    if (detail.model) {
      rows.push({ label: "Capability", value: detail.model.capability });
      rows.push({ label: "Camera pose", value: detail.model.camera_pose });
      rows.push({ label: "Prompt", value: detail.model.prompt_fragment });
      rows.push({ label: "Speed", value: detail.model.speed.toFixed(2) });
      rows.push({ label: "License", value: detail.model.license_class });
    }
    return rows;
  }, [detail]);

  return (
    <StudioScreen
      status={status}
      error={
        notFound
          ? "This motion preset no longer exists. It may have been removed from the catalog."
          : error
      }
      onRetry={() => void load()}
      loadingLabel="Loading motion preset…"
    >
      <Stack.Screen options={{ title: detail?.name ?? "Motion Preset" }} />
      <ScrollView contentContainerStyle={styles.content}>
        {detail ? (
          <>
            <View style={styles.headerCard}>
              <View style={styles.headRow}>
                <Text style={styles.title}>{detail.name}</Text>
                <View style={styles.classBadge}>
                  <Text style={styles.classText}>{detail.render_class}</Text>
                </View>
              </View>
              <Text style={styles.desc}>{detail.description}</Text>
              {detail.tags.length > 0 ? (
                <View style={styles.tagRow}>
                  {detail.tags.map((t) => (
                    <View key={t} style={styles.tag}>
                      <Text style={styles.tagText}>{t}</Text>
                    </View>
                  ))}
                </View>
              ) : null}
            </View>

            <View style={styles.card}>
              <Text style={styles.sectionTitle}>SPEC</Text>
              {specRows.map((row) => (
                <View key={row.label} style={styles.specRow}>
                  <Text style={styles.specLabel}>{row.label}</Text>
                  <Text style={styles.specValue}>{row.value}</Text>
                </View>
              ))}
            </View>

            <View style={styles.card}>
              <Text style={styles.sectionTitle}>APPLY TO A REEL</Text>
              {jobs.length === 0 ? (
                <Text style={styles.mutedNote}>
                  No finished reels yet. You can still compile the plan — it is
                  deterministic and independent of any reel.
                </Text>
              ) : (
                <ScrollView
                  horizontal
                  showsHorizontalScrollIndicator={false}
                  contentContainerStyle={styles.jobRow}
                >
                  {jobs.map((job) => {
                    const active = job.job_id === selectedJobId;
                    return (
                      <Pressable
                        key={job.job_id}
                        style={[styles.jobChip, active && styles.jobChipActive]}
                        onPress={() => setSelectedJobId(job.job_id)}
                        accessibilityRole="button"
                        accessibilityState={{ selected: active }}
                      >
                        <Text
                          style={[
                            styles.jobChipText,
                            active && styles.jobChipTextActive,
                          ]}
                        >
                          Reel {shortId(job.job_id)}
                        </Text>
                      </Pressable>
                    );
                  })}
                </ScrollView>
              )}
            </View>

            <View style={styles.card}>
              <View style={styles.intensityHead}>
                <Text style={styles.sectionTitle}>INTENSITY</Text>
                <Text style={styles.intensityValue}>{intensity}</Text>
              </View>
              <View style={styles.sliderRow}>
                <Pressable
                  style={styles.stepBtn}
                  onPress={() => adjust(-INTENSITY_STEP)}
                  disabled={intensity <= MOTION_INTENSITY_MIN}
                  accessibilityRole="button"
                  accessibilityLabel="Decrease intensity"
                >
                  <Icon name="remove" style={styles.stepBtnText} />
                </Pressable>
                <View style={styles.track}>
                  <View
                    style={[
                      styles.fill,
                      {
                        width: `${
                          ((intensity - MOTION_INTENSITY_MIN) /
                            (MOTION_INTENSITY_MAX - MOTION_INTENSITY_MIN)) *
                          100
                        }%`,
                      },
                    ]}
                  />
                </View>
                <Pressable
                  style={styles.stepBtn}
                  onPress={() => adjust(INTENSITY_STEP)}
                  disabled={intensity >= MOTION_INTENSITY_MAX}
                  accessibilityRole="button"
                  accessibilityLabel="Increase intensity"
                >
                  <Icon name="add" style={styles.stepBtnText} />
                </Pressable>
              </View>

              {actionError ? (
                <Text style={styles.actionError}>{actionError}</Text>
              ) : null}

              <Pressable
                style={[styles.compile, compiling && styles.compileBusy]}
                onPress={confirmCompile}
                disabled={compiling}
                accessibilityRole="button"
              >
                {compiling ? (
                  <ActivityIndicator color={colors.bg} size="small" />
                ) : (
                  <Text style={styles.compileText}>Compile motion plan</Text>
                )}
              </Pressable>
            </View>

            {plan ? (
              <View style={styles.card}>
                <View style={styles.planHead}>
                  <Text style={styles.sectionTitle}>COMPILED PLAN</Text>
                  <Pressable
                    onPress={() => router.push("/studio/motion/history")}
                    hitSlop={8}
                    accessibilityRole="button"
                  >
                    <Text style={styles.historyLink}>View in history</Text>
                  </Pressable>
                </View>
                <View style={styles.specRow}>
                  <Text style={styles.specLabel}>Class</Text>
                  <Text style={styles.specValue}>{plan.motion_class}</Text>
                </View>
                {plan.filter ? (
                  <>
                    <View style={styles.specRow}>
                      <Text style={styles.specLabel}>Filter move</Text>
                      <Text style={styles.specValue}>
                        {plan.filter.camera_motion}
                      </Text>
                    </View>
                    <View style={styles.specRow}>
                      <Text style={styles.specLabel}>Filter intensity</Text>
                      <Text style={styles.specValue}>
                        {plan.filter.intensity}
                      </Text>
                    </View>
                    {plan.filter.effects.length > 0 ? (
                      <View style={styles.specRow}>
                        <Text style={styles.specLabel}>Effects</Text>
                        <Text style={styles.specValue}>
                          {plan.filter.effects.join(", ")}
                        </Text>
                      </View>
                    ) : null}
                  </>
                ) : null}
                {plan.model ? (
                  <>
                    <View style={styles.specRow}>
                      <Text style={styles.specLabel}>Camera pose</Text>
                      <Text style={styles.specValue}>
                        {plan.model.camera_pose}
                      </Text>
                    </View>
                    <View style={styles.specRow}>
                      <Text style={styles.specLabel}>Frame</Text>
                      <Text style={styles.specValue}>
                        {plan.model.width}×{plan.model.height} · {plan.model.length}f
                      </Text>
                    </View>
                    <View style={styles.specRow}>
                      <Text style={styles.specLabel}>Speed</Text>
                      <Text style={styles.specValue}>
                        {plan.model.speed.toFixed(2)}
                      </Text>
                    </View>
                    {plan.model.provider_hints.length > 0 ? (
                      <View style={styles.specRow}>
                        <Text style={styles.specLabel}>Provider hints</Text>
                        <Text style={styles.specValue}>
                          {plan.model.provider_hints.join(", ")}
                        </Text>
                      </View>
                    ) : null}
                  </>
                ) : null}
                {selectedJobId ? (
                  <Text style={styles.planTarget}>
                    Ready to apply to Reel {shortId(selectedJobId)}
                  </Text>
                ) : null}
              </View>
            ) : null}
          </>
        ) : null}
      </ScrollView>
    </StudioScreen>
  );
}

const styles = StyleSheet.create({
  content: { padding: 16, paddingBottom: 48, gap: 12 },
  headerCard: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 8,
  },
  headRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
  },
  title: { flex: 1, color: colors.textPrimary, fontSize: 20, fontWeight: "800" },
  classBadge: {
    borderColor: colors.primary,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 3,
  },
  classText: { color: colors.primary, fontSize: 11, fontWeight: "700" },
  desc: { color: colors.textSecondary, fontSize: 14, lineHeight: 20 },
  tagRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 2 },
  tag: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  tagText: { color: colors.textSecondary, fontSize: 11 },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 8,
  },
  sectionTitle: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 1.2,
  },
  specRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    gap: 12,
    paddingVertical: 2,
  },
  specLabel: { color: colors.muted, fontSize: 13 },
  specValue: {
    flex: 1,
    color: colors.textPrimary,
    fontSize: 13,
    fontWeight: "600",
    textAlign: "right",
  },
  mutedNote: { color: colors.textSecondary, fontSize: 13, lineHeight: 19 },
  jobRow: { gap: 8, paddingVertical: 2, paddingRight: 8 },
  jobChip: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 16,
    paddingVertical: 9,
  },
  jobChipActive: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  jobChipText: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  jobChipTextActive: { color: colors.bg, fontWeight: "700" },
  intensityHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  intensityValue: { color: colors.textPrimary, fontSize: 18, fontWeight: "800" },
  sliderRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    marginTop: 4,
  },
  stepBtn: {
    width: 40,
    height: 40,
    borderRadius: 10,
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  stepBtnText: { color: colors.textPrimary, fontSize: 22, fontWeight: "700" },
  track: {
    flex: 1,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.cardAlt,
    overflow: "hidden",
  },
  fill: { height: "100%", backgroundColor: colors.primary },
  actionError: { color: colors.error, fontSize: 13, marginTop: 4 },
  compile: {
    marginTop: 8,
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
  },
  compileBusy: { opacity: 0.7 },
  compileText: { color: colors.bg, fontSize: 15, fontWeight: "800" },
  planHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  historyLink: { color: colors.primary, fontSize: 13, fontWeight: "700" },
  planTarget: {
    color: colors.success,
    fontSize: 13,
    fontWeight: "700",
    marginTop: 6,
  },
});
