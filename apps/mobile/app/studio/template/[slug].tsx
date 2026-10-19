/**
 * Studio · Template Preview (compile dry-run)
 *
 * Nav manifest: { route: "/studio/template/[slug]", title: "Template Preview" }
 *
 * The missing compile-preview surface. Loads a template's full detail
 * (GET /templates/{slug}), collects the creator's declared inputs + duration +
 * target surface with validation, then calls POST /templates/{slug}/compile to
 * expand it into a timed RenderSpec — a pure DRY-RUN: no job is queued and
 * nothing is created. The resolved output is rendered as reel-level facts
 * (aspect / layout / camera / effects / caption / music / loop) plus a
 * per-segment timeline (absolute timing, captions, audio, media bindings) and
 * any compiler warnings, so a creator can see exactly what a template produces
 * before committing to instantiate.
 *
 * Explicit loading / error (retry) / not-found states. Invalid inputs return a
 * clean 422 surfaced inline. "Reset to defaults" and "Build this in Compose"
 * both confirm before acting.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
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

import { Stack, useLocalSearchParams, useRouter } from "expo-router";

import {
  compileTemplate,
  getTemplate,
  type CompiledRenderSpec,
  type CompiledSegment,
  type TemplateDetail,
  type TemplateInputDef,
} from "@/lib/templates";
import {
  defaultInputValues,
  missingRequiredInputs,
} from "@/src/features/reel-compose/logic";
import { useSession } from "@/src/shared/auth";

import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import { StudioScreen } from "@/components/studio/StudioScreen";

const SURFACES: readonly { id: string; label: string }[] = [
  { id: "tiktok", label: "TikTok" },
  { id: "reels", label: "Reels" },
  { id: "shorts", label: "Shorts" },
];

type CompilePhase = "idle" | "compiling";

function firstParam(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return value[0] ?? "";
  return value ?? "";
}

function clampDuration(value: number, detail: TemplateDetail): number {
  if (!Number.isFinite(value)) return detail.default_duration_s;
  return Math.max(detail.min_duration_s, Math.min(detail.max_duration_s, value));
}

function formatSeconds(value: number): string {
  return `${Number(value.toFixed(2))}s`;
}

export default function StudioTemplatePreviewScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();
  const params = useLocalSearchParams<{ slug?: string | string[] }>();
  const slug = firstParam(params.slug).trim();

  const [detail, setDetail] = useState<TemplateDetail | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [error, setError] = useState("");

  const [values, setValues] = useState<Record<string, string>>({});
  const [durationS, setDurationS] = useState<number>(0);
  const [surface, setSurface] = useState<string | null>(null);

  const [phase, setPhase] = useState<CompilePhase>("idle");
  const [compileError, setCompileError] = useState("");
  const [spec, setSpec] = useState<CompiledRenderSpec | null>(null);

  const load = useCallback(async () => {
    if (!slug) {
      setStatus("error");
      setError("No template was specified.");
      return;
    }
    setStatus("loading");
    try {
      const tmpl = await getTemplate(slug, { token });
      setDetail(tmpl);
      setValues(defaultInputValues(tmpl.inputs));
      setDurationS(tmpl.default_duration_s);
      setSpec(null);
      setCompileError("");
      setStatus("ready");
      setError("");
    } catch (err) {
      setError(describeError(err, "Failed to load this template."));
      setStatus("error");
    }
  }, [slug, token]);

  useEffect(() => {
    void load();
  }, [load]);

  const setValue = useCallback((key: string, next: string) => {
    setValues((prev) => ({ ...prev, [key]: next }));
    setCompileError("");
  }, []);

  const missing = useMemo(
    () => (detail ? missingRequiredInputs(detail.inputs, values) : []),
    [detail, values],
  );

  const canCompile = detail !== null && missing.length === 0 && phase === "idle";

  const onCompile = useCallback(async () => {
    if (!detail) return;
    if (missing.length > 0) {
      setCompileError("Fill in every required field before previewing.");
      return;
    }
    setPhase("compiling");
    setCompileError("");
    try {
      const compiled = await compileTemplate(
        detail.slug,
        {
          inputs: values,
          duration_s: durationS,
          ...(surface ? { surface } : {}),
        },
        { token },
      );
      setSpec(compiled);
    } catch (err) {
      setSpec(null);
      setCompileError(describeError(err, "Could not compile this template."));
    } finally {
      setPhase("idle");
    }
  }, [detail, missing.length, values, durationS, surface, token]);

  const onReset = useCallback(() => {
    if (!detail) return;
    Alert.alert(
      "Reset inputs",
      "Restore every field to the template's suggested defaults?",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Reset",
          style: "destructive",
          onPress: () => {
            setValues(defaultInputValues(detail.inputs));
            setDurationS(detail.default_duration_s);
            setSurface(null);
            setSpec(null);
            setCompileError("");
          },
        },
      ],
    );
  }, [detail]);

  const onBuild = useCallback(() => {
    Alert.alert(
      "Build this reel",
      "Open the Compose flow to turn this template into a real reel job?",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Open Compose",
          onPress: () => router.push("/(tabs)/create"),
        },
      ],
    );
  }, [router]);

  return (
    <StudioScreen
      status={status}
      error={error}
      onRetry={() => void load()}
      loadingLabel="Loading template…"
    >
      <Stack.Screen options={{ title: detail?.name ?? "Template Preview" }} />
      {!detail ? (
        <View style={styles.center}>
          <Text style={styles.notFoundTitle}>Template not found</Text>
          <Pressable
            style={styles.secondary}
            onPress={() => router.back()}
            accessibilityRole="button"
          >
            <Text style={styles.secondaryText}>Back to gallery</Text>
          </Pressable>
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
        >
          <Text style={styles.title}>{detail.name}</Text>
          <Text style={styles.desc}>{detail.description}</Text>
          <Text style={styles.meta}>
            {detail.genre} · {detail.aspect} · {detail.min_duration_s}–
            {detail.max_duration_s}s · {detail.slot_count} shots
            {detail.loopable ? " · loop" : ""}
          </Text>

          <Text style={styles.h2}>Inputs</Text>
          {detail.inputs.length === 0 ? (
            <Text style={styles.metaBlock}>
              This template needs no extra inputs — preview it as-is.
            </Text>
          ) : (
            detail.inputs.map((input) => (
              <InputField
                key={input.key}
                input={input}
                value={values[input.key] ?? ""}
                invalid={missing.includes(input.key)}
                onChange={(next) => setValue(input.key, next)}
              />
            ))
          )}

          <Text style={styles.h2}>
            Duration ({detail.min_duration_s}–{detail.max_duration_s}s)
          </Text>
          <TextInput
            style={styles.input}
            value={String(durationS)}
            onChangeText={(text) => {
              const parsed = Number.parseInt(text.replace(/[^0-9]/g, ""), 10);
              setDurationS(Number.isNaN(parsed) ? 0 : parsed);
              setCompileError("");
            }}
            onBlur={() => setDurationS((d) => clampDuration(d, detail))}
            keyboardType="number-pad"
            placeholderTextColor={colors.muted}
          />

          <Text style={styles.h2}>Target surface (optional)</Text>
          <View style={styles.chips}>
            {SURFACES.map((option) => {
              const active = option.id === surface;
              return (
                <Pressable
                  key={option.id}
                  style={[styles.chip, active && styles.chipActive]}
                  onPress={() => {
                    setSurface(active ? null : option.id);
                    setCompileError("");
                  }}
                  accessibilityRole="button"
                  accessibilityState={{ selected: active }}
                >
                  <Text
                    style={[styles.chipText, active && styles.chipTextActive]}
                  >
                    {option.label}
                  </Text>
                </Pressable>
              );
            })}
          </View>

          {compileError ? (
            <Text style={styles.error}>{compileError}</Text>
          ) : null}

          <Pressable
            style={[styles.primary, !canCompile && styles.disabled]}
            onPress={() => void onCompile()}
            disabled={!canCompile}
            accessibilityRole="button"
          >
            {phase === "compiling" ? (
              <ActivityIndicator color={colors.bg} />
            ) : (
              <Text style={styles.primaryText}>
                {spec ? "Recompile preview" : "Preview compiled spec"}
              </Text>
            )}
          </Pressable>
          <Pressable
            style={styles.linkRow}
            onPress={onReset}
            accessibilityRole="button"
          >
            <Text style={styles.linkText}>Reset to defaults</Text>
          </Pressable>

          {spec ? <CompiledSpecView spec={spec} onBuild={onBuild} /> : null}
          <View style={styles.spacer} />
        </ScrollView>
      )}
    </StudioScreen>
  );
}

interface InputFieldProps {
  input: TemplateInputDef;
  value: string;
  invalid: boolean;
  onChange: (next: string) => void;
}

function InputField({ input, value, invalid, onChange }: InputFieldProps) {
  return (
    <View style={styles.field}>
      <Text style={styles.label}>
        {input.label}
        {input.required ? <Text style={styles.required}> *</Text> : null}
      </Text>
      {input.help ? <Text style={styles.help}>{input.help}</Text> : null}
      {input.choices.length > 0 ? (
        <View style={styles.chips}>
          {input.choices.map((choice) => {
            const active = choice === value;
            return (
              <Pressable
                key={choice}
                style={[styles.chip, active && styles.chipActive]}
                onPress={() => onChange(choice)}
                accessibilityRole="button"
                accessibilityState={{ selected: active }}
              >
                <Text
                  style={[styles.chipText, active && styles.chipTextActive]}
                >
                  {choice}
                </Text>
              </Pressable>
            );
          })}
        </View>
      ) : (
        <TextInput
          style={[styles.input, invalid && styles.inputInvalid]}
          value={value}
          onChangeText={onChange}
          placeholder={input.label}
          placeholderTextColor={colors.muted}
          multiline
        />
      )}
    </View>
  );
}

interface CompiledSpecViewProps {
  spec: CompiledRenderSpec;
  onBuild: () => void;
}

function CompiledSpecView({ spec, onBuild }: CompiledSpecViewProps) {
  const facts: { label: string; value: string }[] = useMemo(() => {
    const out: { label: string; value: string }[] = [
      { label: "Version", value: spec.template_version || "—" },
      { label: "Aspect", value: spec.aspect || "—" },
      { label: "Layout", value: spec.layout || "—" },
      { label: "Duration", value: formatSeconds(spec.duration_s) },
      { label: "Segments", value: String(spec.segments.length) },
      { label: "Camera", value: spec.camera_motion || "none" },
      {
        label: "Motion path",
        value: spec.motion_preset
          ? `${spec.motion_class} · ${spec.motion_preset}`
          : spec.motion_class,
      },
      { label: "VFX intensity", value: `${spec.vfx_intensity}` },
      { label: "Caption style", value: spec.caption_style || "—" },
      { label: "Audio bed", value: spec.audio_foreground || "—" },
      { label: "Duck music", value: spec.duck ? "Yes" : "No" },
      {
        label: "Loop",
        value: spec.loop.enabled ? "Seamless loop" : "No loop",
      },
    ];
    if (spec.effects.length > 0) {
      out.push({ label: "Effects", value: spec.effects.join(", ") });
    }
    if (spec.music_prompt.trim()) {
      out.push({ label: "Music prompt", value: spec.music_prompt.trim() });
    }
    if (spec.background_id.trim()) {
      out.push({ label: "Background", value: spec.background_id.trim() });
    }
    if (spec.trend_relink) {
      out.push({ label: "Trend audio", value: "Relink on publish" });
    }
    return out;
  }, [spec]);

  return (
    <View style={styles.result}>
      <Text style={styles.resultEyebrow}>DRY-RUN PREVIEW</Text>
      <Text style={styles.resultTitle}>Compiled render-spec</Text>
      <Text style={styles.resultSub}>
        Nothing was queued — this is the exact plan this template would build.
      </Text>

      {spec.warnings.length > 0 ? (
        <View style={styles.warnBox}>
          <Text style={styles.warnTitle}>
            {spec.warnings.length}{" "}
            {spec.warnings.length === 1 ? "warning" : "warnings"}
          </Text>
          {spec.warnings.map((w, index) => (
            <Text key={`${index}-${w}`} style={styles.warnText}>
              • {w}
            </Text>
          ))}
        </View>
      ) : null}

      <View style={styles.rows}>
        {facts.map((fact) => (
          <View key={fact.label} style={styles.row}>
            <Text style={styles.rowLabel}>{fact.label}</Text>
            <Text style={styles.rowValue} selectable numberOfLines={3}>
              {fact.value}
            </Text>
          </View>
        ))}
      </View>

      <Text style={styles.h2}>Timeline</Text>
      {spec.segments.length === 0 ? (
        <Text style={styles.metaBlock}>The compiler produced no segments.</Text>
      ) : (
        spec.segments.map((segment) => (
          <SegmentCard
            key={`${segment.order}-${segment.role}`}
            segment={segment}
          />
        ))
      )}

      <Pressable
        style={styles.buildButton}
        onPress={onBuild}
        accessibilityRole="button"
      >
        <Text style={styles.buildText}>Build this in Compose</Text>
      </Pressable>
    </View>
  );
}

function SegmentCard({ segment }: { segment: CompiledSegment }) {
  const audio = segment.audio
    .map((cue) => (cue.ducked ? `${cue.layer} (ducked)` : cue.layer))
    .join(", ");
  const media = segment.media
    .map((binding) => `${binding.track}:${binding.kind}`)
    .join(", ");
  const transitions =
    segment.transition_in === segment.transition_out
      ? segment.transition_in
      : `${segment.transition_in} → ${segment.transition_out}`;

  return (
    <View style={styles.segment}>
      <View style={styles.segmentHead}>
        <Text style={styles.segmentOrder}>{segment.order + 1}</Text>
        <View style={styles.segmentHeadText}>
          <Text style={styles.segmentTitle}>
            {segment.label || segment.role}
          </Text>
          <Text style={styles.segmentTiming}>
            {formatSeconds(segment.t_start)} – {formatSeconds(segment.t_end)} ·{" "}
            {segment.track}
          </Text>
        </View>
        {segment.hook_gate ? (
          <View style={styles.hookBadge}>
            <Text style={styles.hookBadgeText}>HOOK</Text>
          </View>
        ) : null}
      </View>
      {segment.caption?.text ? (
        <Text style={styles.segmentCaption} numberOfLines={3}>
          “{segment.caption.text}”
        </Text>
      ) : null}
      <View style={styles.segmentFacts}>
        <Text style={styles.segmentMeta}>Transition: {transitions}</Text>
        {media ? (
          <Text style={styles.segmentMeta}>Media: {media}</Text>
        ) : null}
        {audio ? (
          <Text style={styles.segmentMeta}>Audio: {audio}</Text>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  content: { padding: 16, paddingBottom: 48, gap: 8 },
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
    gap: 12,
  },
  title: { color: colors.textPrimary, fontSize: 22, fontWeight: "800" },
  desc: { color: colors.textSecondary, fontSize: 14, lineHeight: 20 },
  meta: { color: colors.muted, fontSize: 12, marginBottom: 4 },
  metaBlock: { color: colors.muted, fontSize: 13, lineHeight: 18 },
  h2: {
    color: colors.textPrimary,
    fontSize: 16,
    fontWeight: "700",
    marginTop: 14,
  },
  field: { gap: 4, marginTop: 6 },
  label: { color: colors.textPrimary, fontSize: 14, fontWeight: "600" },
  required: { color: colors.error },
  help: { color: colors.muted, fontSize: 12 },
  input: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    color: colors.textPrimary,
    fontSize: 16,
    paddingHorizontal: 14,
    paddingVertical: 12,
    minHeight: 48,
    textAlignVertical: "top",
  },
  inputInvalid: { borderColor: colors.error },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  chipTextActive: { color: colors.bg, fontWeight: "700" },
  error: { color: colors.error, fontSize: 14, marginTop: 8 },
  primary: {
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingVertical: 15,
    alignItems: "center",
    marginTop: 16,
  },
  disabled: { opacity: 0.5 },
  primaryText: { color: colors.bg, fontSize: 15, fontWeight: "700" },
  linkRow: { alignItems: "center", paddingVertical: 12 },
  linkText: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  result: { marginTop: 12, gap: 8 },
  resultEyebrow: {
    color: colors.accent,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 1.1,
  },
  resultTitle: { color: colors.textPrimary, fontSize: 18, fontWeight: "800" },
  resultSub: { color: colors.muted, fontSize: 12, lineHeight: 17 },
  warnBox: {
    backgroundColor: colors.card,
    borderColor: colors.accent,
    borderWidth: 1,
    borderRadius: 10,
    padding: 12,
    gap: 4,
    marginTop: 4,
  },
  warnTitle: { color: colors.accent, fontSize: 13, fontWeight: "700" },
  warnText: { color: colors.textSecondary, fontSize: 12, lineHeight: 17 },
  rows: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 14,
    overflow: "hidden",
    marginTop: 4,
  },
  row: {
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderBottomColor: colors.border,
    borderBottomWidth: StyleSheet.hairlineWidth,
    gap: 3,
  },
  rowLabel: {
    color: colors.muted,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.8,
    textTransform: "uppercase",
  },
  rowValue: { color: colors.textPrimary, fontSize: 15 },
  segment: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    gap: 8,
    marginTop: 8,
  },
  segmentHead: { flexDirection: "row", alignItems: "center", gap: 10 },
  segmentOrder: {
    color: colors.accent,
    fontSize: 16,
    fontWeight: "800",
    minWidth: 22,
    textAlign: "center",
  },
  segmentHeadText: { flex: 1, gap: 2 },
  segmentTitle: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  segmentTiming: { color: colors.muted, fontSize: 12 },
  hookBadge: {
    backgroundColor: colors.accent,
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  hookBadgeText: { color: colors.bg, fontSize: 10, fontWeight: "800" },
  segmentCaption: {
    color: colors.textSecondary,
    fontSize: 13,
    fontStyle: "italic",
    lineHeight: 18,
  },
  segmentFacts: { gap: 3 },
  segmentMeta: { color: colors.muted, fontSize: 12 },
  buildButton: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
    marginTop: 16,
  },
  buildText: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  notFoundTitle: { color: colors.textPrimary, fontSize: 18, fontWeight: "700" },
  secondary: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
  secondaryText: {
    color: colors.textSecondary,
    fontSize: 14,
    fontWeight: "600",
  },
  spacer: { height: 24 },
});
