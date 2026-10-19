/**
 * Trim & export. Preview a completed reel (expo-av), set an in/out range + speed,
 * and export the cut via the non-destructive editor timeline. Pass the reel via
 * route params: `/capture/trim?jobId=…&url=…&duration=…` (the reel detail
 * screens link here). Without a jobId it lists the creator's finished reels to
 * pick one from.
 */

import * as React from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { ResizeMode, Video } from "expo-av";
import { router, useLocalSearchParams } from "expo-router";

import { colors } from "@/components/me/theme";
import { useSession } from "@/src/shared/auth";
import { ProExportAccess, useRevenueCat } from "@/src/shared/billing";
import { exportTimeline } from "@/lib/editor";
import { ApiError, listJobs } from "@/lib/api";
import { JobState, type Job } from "@/lib/types";
import { jobResultUrl } from "@/src/shared/media";
import { Icon } from "@/components/ui/Icon";

function clampInt(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, Math.round(v * 10) / 10));
}

export default function TrimScreen() {
  const { apiKey } = useSession();
  const { requireProExport } = useRevenueCat();
  const token = apiKey ?? undefined;
  const params = useLocalSearchParams<{ jobId?: string; url?: string; duration?: string }>();
  const jobId = typeof params.jobId === "string" ? params.jobId : "";
  const url = typeof params.url === "string" ? params.url : "";
  const total = Math.max(1, Number(params.duration ?? 30) || 30);

  const [inS, setInS] = React.useState(0);
  const [outS, setOutS] = React.useState(Math.min(total, 15));
  const [speed, setSpeed] = React.useState(1.0);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const onExport = React.useCallback(async () => {
    if (!jobId || outS <= inS) return;
    setBusy(true);
    setError("");
    try {
      const access = await requireProExport();
      if (!access.allowed) {
        setError(access.snapshot.message);
        return;
      }
      const job = await exportTimeline(
        jobId,
        { segments: [{ source_in: inS, source_out: outS, speed }] },
        { token },
      );
      router.push(`/job/${job.job_id}` as never);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export failed.");
    } finally {
      setBusy(false);
    }
  }, [jobId, inS, outS, speed, token, requireProExport]);

  if (!jobId) {
    return <TrimReelPicker token={token} />;
  }

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      {url ? (
        <Video
          source={{ uri: url }}
          style={styles.video}
          useNativeControls
          resizeMode={ResizeMode.CONTAIN}
          isLooping
        />
      ) : (
        <View style={[styles.video, styles.noVideo]}>
          <Text style={styles.meta}>No preview URL — controls still export the cut.</Text>
        </View>
      )}

      <Stepper label="In (s)" value={inS} min={0} max={outS - 0.5} step={0.5}
        onChange={(v) => setInS(clampInt(v, 0, outS - 0.5))} />
      <Stepper label="Out (s)" value={outS} min={inS + 0.5} max={total} step={0.5}
        onChange={(v) => setOutS(clampInt(v, inS + 0.5, total))} />
      <Stepper label="Speed ×" value={speed} min={0.25} max={4} step={0.25}
        onChange={(v) => setSpeed(clampInt(v, 0.25, 4))} />

      <Text style={styles.meta}>
        Clip: {(outS - inS).toFixed(1)}s at {speed}× → ~{((outS - inS) / speed).toFixed(1)}s output
      </Text>

      <ProExportAccess />

      <Pressable
        style={[styles.button, (busy || outS <= inS) && styles.buttonDisabled]}
        onPress={onExport}
        disabled={busy || outS <= inS}
      >
        {busy ? (
          <ActivityIndicator color={colors.bg} />
        ) : (
          <Text style={styles.buttonText}>Export cut with Pro</Text>
        )}
      </Pressable>

      {error ? <Text style={styles.error}>{error}</Text> : null}
      <View style={styles.spacer} />
    </ScrollView>
  );
}

function Stepper({ label, value, min, max, step, onChange }:
  { label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void }) {
  return (
    <View style={styles.stepper}>
      <Text style={styles.stepLabel}>{label}</Text>
      <View style={styles.stepControls}>
        <Pressable style={styles.stepBtn} onPress={() => onChange(Math.max(min, value - step))}>
          <Icon name="remove" style={styles.stepBtnText} />
        </Pressable>
        <Text style={styles.stepValue}>{value.toFixed(step < 1 ? 1 : 0)}</Text>
        <Pressable style={styles.stepBtn} onPress={() => onChange(Math.min(max, value + step))}>
          <Icon name="add" style={styles.stepBtnText} />
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  reelRow: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 10,
  },
  reelTitle: { color: colors.textPrimary, fontSize: 15, fontWeight: "600" },
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  intro: { color: colors.textSecondary, fontSize: 14, marginBottom: 16 },
  video: { width: "100%", height: 300, borderRadius: 12, backgroundColor: colors.card },
  noVideo: { alignItems: "center", justifyContent: "center", borderColor: colors.border, borderWidth: 1 },
  stepper: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    backgroundColor: colors.card, borderColor: colors.border, borderWidth: 1,
    borderRadius: 12, padding: 12, marginTop: 12,
  },
  stepLabel: { color: colors.textPrimary, fontSize: 14, fontWeight: "600" },
  stepControls: { flexDirection: "row", alignItems: "center", gap: 14 },
  stepBtn: {
    width: 36, height: 36, borderRadius: 10, backgroundColor: colors.cardAlt,
    alignItems: "center", justifyContent: "center",
  },
  stepBtnText: { color: colors.textPrimary, fontSize: 20, fontWeight: "700" },
  stepValue: { color: colors.textPrimary, fontSize: 16, minWidth: 44, textAlign: "center" },
  meta: { color: colors.muted, fontSize: 12, marginTop: 14 },
  button: {
    backgroundColor: colors.primary, borderRadius: 12, paddingVertical: 12,
    alignItems: "center", justifyContent: "center", marginTop: 16,
  },
  buttonDisabled: { opacity: 0.5 },
  buttonText: { color: colors.bg, fontSize: 15, fontWeight: "600" },
  error: { color: colors.error, fontSize: 14, marginTop: 12 },
  spacer: { height: 24 },
});

interface TrimReelPickerProps {
  readonly token?: string;
}

/** Finished reels (with a clean result) the creator can trim. */
function TrimReelPicker({ token }: TrimReelPickerProps) {
  const [reels, setReels] = React.useState<{ job: Job; url: string }[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");

  const load = React.useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const jobs = await listJobs({ token });
      setReels(
        jobs
          .filter((job) => job.state === JobState.Complete)
          .map((job) => ({ job, url: jobResultUrl(job) ?? "" }))
          .filter((row) => row.url.length > 0),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load your reels.");
    } finally {
      setLoading(false);
    }
  }, [token]);

  React.useEffect(() => {
    void load();
  }, [load]);

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.intro}>Pick a finished reel to trim.</Text>
      {loading ? (
        <ActivityIndicator color={colors.primary} />
      ) : error ? (
        <>
          <Text style={styles.error}>{error}</Text>
          <Pressable style={styles.button} onPress={() => void load()}>
            <Text style={styles.buttonText}>Try again</Text>
          </Pressable>
        </>
      ) : reels.length === 0 ? (
        <>
          <Text style={styles.meta}>
            No finished reels yet. Once a reel completes it shows up here, ready to
            cut.
          </Text>
          <Pressable style={styles.button} onPress={() => router.push("/(tabs)/create")}>
            <Text style={styles.buttonText}>Create a reel</Text>
          </Pressable>
        </>
      ) : (
        reels.map(({ job, url }) => (
          <Pressable
            key={job.job_id}
            style={styles.reelRow}
            onPress={() =>
              router.push(
                `/capture/trim?jobId=${encodeURIComponent(job.job_id)}&url=${encodeURIComponent(url)}`,
              )
            }
            accessibilityRole="button"
            accessibilityLabel={`Trim ${job.hook?.trim() || job.job_id}`}
          >
            <Text style={styles.reelTitle} numberOfLines={2}>
              {job.hook?.trim() || job.job_id}
            </Text>
          </Pressable>
        ))
      )}
    </ScrollView>
  );
}
