/**
 * Multi-segment timeline editor (OpenCut-style). Assemble a finished reel into an
 * ordered list of trimmed segments — each with its own in/out, speed, and burned
 * caption — plus text overlays on a wall-clock track, then export the whole
 * timeline via the non-destructive editor (`exportTimeline`). Route params:
 * `/editor?jobId=…&url=…&duration=…`. Without a jobId it lists the creator's
 * finished reels so the editor is a working entry point from any menu.
 *
 * This is the mobile counterpart to the web timeline editor and completes the
 * "users can edit video" journey: trim + reorder + caption + overlay → new render.
 */

import * as React from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { ResizeMode, Video } from "expo-av";
import { router, useLocalSearchParams } from "expo-router";

import { colors } from "@/components/me/theme";
import { useSession } from "@/src/shared/auth";
import { ProExportAccess, useRevenueCat } from "@/src/shared/billing";
import { exportTimeline, type TextOverlay, type TimelineSegment } from "@/lib/editor";
import { Icon } from "@/components/ui/Icon";
import { EditorJobPicker } from "@/components/editor/EditorJobPicker";
import { GenerationErrorNotice } from "@/components/billing/GenerationErrorNotice";

type OverlayPos = "top" | "center" | "bottom";

interface SegmentDraft extends TimelineSegment {
  id: string;
}

interface OverlayDraft extends TextOverlay {
  id: string;
}

function round1(v: number): number {
  return Math.round(v * 10) / 10;
}

/** Sum of per-segment output durations (each source span divided by its speed). */
function timelineOutputSeconds(segments: readonly SegmentDraft[]): number {
  return segments.reduce((acc, s) => {
    const span = Math.max(0, s.source_out - s.source_in);
    return acc + span / (s.speed && s.speed > 0 ? s.speed : 1);
  }, 0);
}

export default function EditorScreen() {
  const { apiKey } = useSession();
  const { requireProExport } = useRevenueCat();
  const token = apiKey ?? undefined;
  const params = useLocalSearchParams<{ jobId?: string; url?: string; duration?: string }>();
  const jobId = typeof params.jobId === "string" ? params.jobId : "";
  const url = typeof params.url === "string" ? params.url : "";
  const total = Math.max(1, Number(params.duration ?? 30) || 30);

  // Nondeterministic-clock APIs (Date.now) are avoided; a counter yields stable keys.
  const nextId = React.useRef(0);
  const mkId = React.useCallback((prefix: string) => `${prefix}-${nextId.current++}`, []);

  const [segments, setSegments] = React.useState<SegmentDraft[]>(() => [
    { id: "seg-init", source_in: 0, source_out: Math.min(total, 8), speed: 1, caption: null },
  ]);
  const [overlays, setOverlays] = React.useState<OverlayDraft[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const addSegment = React.useCallback(() => {
    setSegments((prev) => {
      const last = prev[prev.length - 1];
      const start = last ? Math.min(total - 0.5, last.source_out) : 0;
      return [
        ...prev,
        { id: mkId("seg"), source_in: round1(start), source_out: round1(Math.min(total, start + 5)), speed: 1, caption: null },
      ];
    });
  }, [total, mkId]);

  const patchSegment = React.useCallback((id: string, patch: Partial<TimelineSegment>) => {
    setSegments((prev) => prev.map((s) => (s.id === id ? { ...s, ...patch } : s)));
  }, []);

  const removeSegment = React.useCallback((id: string) => {
    setSegments((prev) => (prev.length <= 1 ? prev : prev.filter((s) => s.id !== id)));
  }, []);

  const moveSegment = React.useCallback((id: string, dir: -1 | 1) => {
    setSegments((prev) => {
      const i = prev.findIndex((s) => s.id === id);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= prev.length) return prev;
      const next = [...prev];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  }, []);

  const addOverlay = React.useCallback(() => {
    setOverlays((prev) => [
      ...prev,
      { id: mkId("ov"), text: "New caption", start_s: 0, end_s: 3, position: "bottom" },
    ]);
  }, [mkId]);

  const patchOverlay = React.useCallback((id: string, patch: Partial<TextOverlay>) => {
    setOverlays((prev) => prev.map((o) => (o.id === id ? { ...o, ...patch } : o)));
  }, []);

  const removeOverlay = React.useCallback((id: string) => {
    setOverlays((prev) => prev.filter((o) => o.id !== id));
  }, []);

  const invalidSegment = segments.some((s) => s.source_out <= s.source_in);
  const canAttemptExport =
    Boolean(jobId) && segments.length > 0 && !invalidSegment && !busy;

  const onExport = React.useCallback(async () => {
    if (!jobId || invalidSegment) return;
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
        {
          segments: segments.map(({ id: _id, ...s }) => ({
            ...s,
            caption: s.caption?.trim() ? s.caption.trim() : null,
          })),
          overlays: overlays.length
            ? overlays.map(({ id: _id, ...o }) => ({ ...o, text: o.text.trim() }))
                .filter((o) => o.text.length > 0)
            : undefined,
        },
        { token },
      );
      router.push(`/job/${job.job_id}` as never);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Timeline export failed.");
    } finally {
      setBusy(false);
    }
  }, [jobId, invalidSegment, segments, overlays, token, requireProExport]);

  if (!jobId) {
    return (
      <ScrollView style={styles.container} contentContainerStyle={styles.content}>
        <EditorJobPicker />
      </ScrollView>
    );
  }

  const outputS = timelineOutputSeconds(segments);

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      {url ? (
        <Video source={{ uri: url }} style={styles.video} useNativeControls resizeMode={ResizeMode.CONTAIN} isLooping />
      ) : (
        <View style={[styles.video, styles.noVideo]}>
          <Text style={styles.meta}>No preview URL — the timeline still exports.</Text>
        </View>
      )}

      <View style={styles.sectionHeader}>
        <Text style={styles.sectionTitle}>Segments ({segments.length})</Text>
        <Pressable style={styles.addBtn} onPress={addSegment}>
          <Icon name="add" size={16} color={colors.textPrimary} />
          <Text style={styles.addBtnText}>Add</Text>
        </Pressable>
      </View>

      {segments.map((s, idx) => (
        <View key={s.id} style={styles.card}>
          <View style={styles.cardHeader}>
            <Text style={styles.cardTitle}>#{idx + 1}</Text>
            <View style={styles.rowGap}>
              <Pressable style={styles.iconBtn} disabled={idx === 0} onPress={() => moveSegment(s.id, -1)}>
                <Icon name="arrow-up" style={[styles.iconBtnText, idx === 0 && styles.disabledText]} />
              </Pressable>
              <Pressable style={styles.iconBtn} disabled={idx === segments.length - 1} onPress={() => moveSegment(s.id, 1)}>
                <Icon name="arrow-down" style={[styles.iconBtnText, idx === segments.length - 1 && styles.disabledText]} />
              </Pressable>
              <Pressable style={styles.iconBtn} disabled={segments.length <= 1} onPress={() => removeSegment(s.id)}>
                <Icon name="close" style={[styles.iconBtnText, segments.length <= 1 && styles.disabledText]} />
              </Pressable>
            </View>
          </View>

          <Stepper label="In (s)" value={s.source_in} min={0} max={s.source_out - 0.5} step={0.5}
            onChange={(v) => patchSegment(s.id, { source_in: round1(Math.max(0, Math.min(s.source_out - 0.5, v))) })} />
          <Stepper label="Out (s)" value={s.source_out} min={s.source_in + 0.5} max={total} step={0.5}
            onChange={(v) => patchSegment(s.id, { source_out: round1(Math.max(s.source_in + 0.5, Math.min(total, v))) })} />
          <Stepper label="Speed ×" value={s.speed ?? 1} min={0.25} max={4} step={0.25}
            onChange={(v) => patchSegment(s.id, { speed: round1(Math.max(0.25, Math.min(4, v))) })} />

          <TextInput
            style={styles.input}
            placeholder="Burned caption (optional)"
            placeholderTextColor={colors.muted}
            value={s.caption ?? ""}
            onChangeText={(t) => patchSegment(s.id, { caption: t })}
          />
          {s.source_out <= s.source_in ? <Text style={styles.error}>Out must be after In.</Text> : null}
        </View>
      ))}

      <View style={styles.sectionHeader}>
        <Text style={styles.sectionTitle}>Text overlays ({overlays.length})</Text>
        <Pressable style={styles.addBtn} onPress={addOverlay}>
          <Icon name="add" size={16} color={colors.textPrimary} />
          <Text style={styles.addBtnText}>Add</Text>
        </Pressable>
      </View>

      {overlays.map((o) => (
        <View key={o.id} style={styles.card}>
          <View style={styles.cardHeader}>
            <TextInput
              style={[styles.input, styles.overlayInput]}
              placeholder="Overlay text"
              placeholderTextColor={colors.muted}
              value={o.text}
              onChangeText={(t) => patchOverlay(o.id, { text: t })}
            />
            <Pressable style={styles.iconBtn} onPress={() => removeOverlay(o.id)}>
              <Icon name="close" style={styles.iconBtnText} />
            </Pressable>
          </View>
          <Stepper label="Start (s)" value={o.start_s} min={0} max={Math.max(0, o.end_s - 0.5)} step={0.5}
            onChange={(v) => patchOverlay(o.id, { start_s: round1(Math.max(0, Math.min(o.end_s - 0.5, v))) })} />
          <Stepper label="End (s)" value={o.end_s} min={o.start_s + 0.5} max={Math.ceil(outputS) + 5} step={0.5}
            onChange={(v) => patchOverlay(o.id, { end_s: round1(Math.max(o.start_s + 0.5, v)) })} />
          <View style={styles.posRow}>
            {(["top", "center", "bottom"] as OverlayPos[]).map((p) => (
              <Pressable
                key={p}
                style={[styles.posBtn, o.position === p && styles.posBtnActive]}
                onPress={() => patchOverlay(o.id, { position: p })}
              >
                <Text style={[styles.posBtnText, o.position === p && styles.posBtnTextActive]}>{p}</Text>
              </Pressable>
            ))}
          </View>
        </View>
      ))}

      <Text style={styles.meta}>
        {segments.length} segment{segments.length === 1 ? "" : "s"} → ~{outputS.toFixed(1)}s output
        {overlays.length ? ` · ${overlays.length} overlay${overlays.length === 1 ? "" : "s"}` : ""}
      </Text>

      <ProExportAccess />

      <Pressable
        style={[styles.button, !canAttemptExport && styles.buttonDisabled]}
        onPress={onExport}
        disabled={!canAttemptExport}
      >
        {busy ? (
          <ActivityIndicator color={colors.bg} />
        ) : (
          <Text style={styles.buttonText}>Export timeline with Pro</Text>
        )}
      </Pressable>

      <GenerationErrorNotice message={error} style={styles.error} />
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
        <Pressable
          style={styles.stepBtn}
          onPress={() => onChange(Math.max(min, value - step))}
          accessibilityRole="button"
          accessibilityLabel={`Decrease ${label}`}
        >
          <Icon name="remove" size={18} color={colors.textPrimary} />
        </Pressable>
        <Text style={styles.stepValue}>{value.toFixed(step < 1 ? 1 : 0)}</Text>
        <Pressable
          style={styles.stepBtn}
          onPress={() => onChange(Math.min(max, value + step))}
          accessibilityRole="button"
          accessibilityLabel={`Increase ${label}`}
        >
          <Icon name="add" size={18} color={colors.textPrimary} />
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  title: { color: colors.textPrimary, fontSize: 20, fontWeight: "700", marginBottom: 8 },
  intro: { color: colors.textSecondary, fontSize: 14, marginBottom: 16 },
  video: { width: "100%", height: 260, borderRadius: 12, backgroundColor: colors.card },
  noVideo: { alignItems: "center", justifyContent: "center", borderColor: colors.border, borderWidth: 1 },
  sectionHeader: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 20, marginBottom: 8,
  },
  sectionTitle: { color: colors.textPrimary, fontSize: 16, fontWeight: "700" },
  addBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: colors.cardAlt, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 6,
  },
  addBtnText: { color: colors.textPrimary, fontSize: 13, fontWeight: "600" },
  card: {
    backgroundColor: colors.card, borderColor: colors.border, borderWidth: 1,
    borderRadius: 12, padding: 12, marginBottom: 10,
  },
  cardHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 4 },
  cardTitle: { color: colors.textPrimary, fontSize: 14, fontWeight: "700" },
  rowGap: { flexDirection: "row", gap: 8 },
  iconBtn: {
    width: 32, height: 32, borderRadius: 8, backgroundColor: colors.cardAlt,
    alignItems: "center", justifyContent: "center",
  },
  iconBtnText: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  disabledText: { opacity: 0.3 },
  stepper: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    marginTop: 8,
  },
  stepLabel: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  stepControls: { flexDirection: "row", alignItems: "center", gap: 12 },
  stepBtn: {
    width: 32, height: 32, borderRadius: 8, backgroundColor: colors.cardAlt,
    alignItems: "center", justifyContent: "center",
  },
  stepValue: { color: colors.textPrimary, fontSize: 15, minWidth: 42, textAlign: "center" },
  input: {
    backgroundColor: colors.cardAlt, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 8,
    color: colors.textPrimary, fontSize: 14, marginTop: 10,
  },
  overlayInput: { flex: 1, marginTop: 0, marginRight: 8 },
  posRow: { flexDirection: "row", gap: 8, marginTop: 10 },
  posBtn: {
    flex: 1, borderRadius: 10, paddingVertical: 8, backgroundColor: colors.cardAlt,
    alignItems: "center", borderColor: colors.border, borderWidth: 1,
  },
  posBtnActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  posBtnText: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  posBtnTextActive: { color: colors.bg },
  meta: { color: colors.muted, fontSize: 12, marginTop: 16 },
  button: {
    backgroundColor: colors.primary, borderRadius: 12, paddingVertical: 12,
    alignItems: "center", justifyContent: "center", marginTop: 16,
  },
  buttonDisabled: { opacity: 0.5 },
  buttonText: { color: colors.bg, fontSize: 15, fontWeight: "600" },
  error: { color: colors.error, fontSize: 13, marginTop: 8 },
  spacer: { height: 32 },
});
