/**
 * Experiments (mobile) — the first SERVER-PERSISTED experiment surface: a
 * 1-body/N-hooks retention A/B. Hold the body constant, vary ONLY the hook
 * across N variants, feed each variant's real retention metrics back to the API,
 * then let the SERVER compute + persist the retention-weighted winner.
 *
 * Wired to the real publishing-experiments routes via `@/lib/experiments`:
 *   POST /experiments                              create (key, 2..20 hooks, body_ref)
 *   GET  /experiments/{key}                        experiment + variants + verdict
 *   POST /experiments/{key}/variants/{id}/metrics  ingest a variant's retention snapshot
 *   POST /experiments/{key}/evaluate               persist + return the winner
 *
 * Distinct from the pure-client `ab-lab` / `retention-lab` screens (which run
 * `@reelforge/growth-analytics` locally and submit nothing).
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

import { colors } from "@/components/me/theme";
import { ApiError, isAbortError, makeAbortError } from "@/src/shared/api";
import { useSession } from "@/src/shared/auth";
import {
  MAX_HOOKS,
  MIN_HOOKS,
  createExperiment,
  evaluateExperiment,
  getExperiment,
  ingestMetrics,
  parseHookRefs,
  type Experiment,
  type ExperimentVariant,
  type MetricsBody,
} from "@/lib/experiments";

type Phase = "idle" | "loading" | "ready" | "error";
type Busy = "none" | "load" | "create" | "evaluate";

function pct(value: number): string {
  return `${Math.round((Number.isFinite(value) ? value : 0) * 100)}%`;
}

/** A rate the platform may not report: null is "not measured", never 0%. */
export function measuredPct(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "not measured";
  }
  return pct(value);
}

/** Blank input means "not reported"; anything else is clamped to 0..1. */
export function optionalRatio(raw: string): number | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const value = Number(trimmed);
  return Number.isFinite(value) ? clamp01(value) : null;
}

export function ExperimentsScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const [keyInput, setKeyInput] = React.useState("");
  const [bodyRef, setBodyRef] = React.useState("");
  const [hooksText, setHooksText] = React.useState("");

  const [experiment, setExperiment] = React.useState<Experiment | null>(null);
  const [phase, setPhase] = React.useState<Phase>("idle");
  const [busy, setBusy] = React.useState<Busy>("none");
  const [error, setError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);

  const inFlight = React.useRef<AbortController | null>(null);

  React.useEffect(
    () => () => inFlight.current?.abort(makeAbortError()),
    [],
  );

  const errorText = React.useCallback((err: unknown, fallback: string): string => {
    if (err instanceof ApiError) return err.message;
    if (err instanceof Error) return err.message;
    return fallback;
  }, []);

  const hookRefs = React.useMemo(() => parseHookRefs(hooksText), [hooksText]);

  const load = React.useCallback(
    async (rawKey: string) => {
      const key = rawKey.trim();
      if (!key) {
        setError("Enter an experiment key to load.");
        return;
      }
      inFlight.current?.abort(makeAbortError());
      const controller = new AbortController();
      inFlight.current = controller;

      setBusy("load");
      setPhase(experiment ? phase : "loading");
      setError(null);
      setNotice(null);
      try {
        const exp = await getExperiment(key, { token, signal: controller.signal });
        if (controller.signal.aborted) return;
        setExperiment(exp);
        setPhase("ready");
      } catch (err) {
        if (isAbortError(err) || controller.signal.aborted) return;
        if (err instanceof ApiError && err.status === 404) {
          setExperiment(null);
          setPhase("idle");
          setNotice(`No experiment "${key}" yet — create it below.`);
        } else {
          setError(errorText(err, "Failed to load the experiment."));
          setPhase("error");
        }
      } finally {
        if (inFlight.current === controller) inFlight.current = null;
        setBusy("none");
      }
    },
    [token, experiment, phase, errorText],
  );

  const create = React.useCallback(async () => {
    const key = keyInput.trim();
    if (!key) {
      setError("An experiment key is required.");
      return;
    }
    if (hookRefs.length < MIN_HOOKS) {
      setError(`Add at least ${MIN_HOOKS} hooks (one per line).`);
      return;
    }
    if (hookRefs.length > MAX_HOOKS) {
      setError(`At most ${MAX_HOOKS} hooks are allowed.`);
      return;
    }
    inFlight.current?.abort(makeAbortError());
    const controller = new AbortController();
    inFlight.current = controller;

    setBusy("create");
    setError(null);
    setNotice(null);
    try {
      const exp = await createExperiment(
        { experiment_key: key, hook_refs: hookRefs, body_ref: bodyRef.trim() },
        { token, signal: controller.signal, idempotencyKey: `exp-${key}` },
      );
      if (controller.signal.aborted) return;
      setExperiment(exp);
      setPhase("ready");
      setHooksText("");
      setNotice("Experiment created. Log per-variant metrics, then evaluate.");
    } catch (err) {
      if (isAbortError(err) || controller.signal.aborted) return;
      setError(errorText(err, "Failed to create the experiment."));
    } finally {
      if (inFlight.current === controller) inFlight.current = null;
      setBusy("none");
    }
  }, [keyInput, hookRefs, bodyRef, token, errorText]);

  const evaluate = React.useCallback(async () => {
    if (!experiment) return;
    inFlight.current?.abort(makeAbortError());
    const controller = new AbortController();
    inFlight.current = controller;

    setBusy("evaluate");
    setError(null);
    setNotice(null);
    try {
      const exp = await evaluateExperiment(experiment.experiment_key, {
        token,
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      setExperiment(exp);
      setNotice(
        exp.winner_hook_ref
          ? `Winner: ${exp.winner_hook_ref}`
          : "Inconclusive — needs more views or a wider margin.",
      );
    } catch (err) {
      if (isAbortError(err) || controller.signal.aborted) return;
      setError(errorText(err, "Failed to evaluate the experiment."));
    } finally {
      if (inFlight.current === controller) inFlight.current = null;
      setBusy("none");
    }
  }, [experiment, token, errorText]);

  const onMetricsSaved = React.useCallback(() => {
    if (experiment) void load(experiment.experiment_key);
  }, [experiment, load]);

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.intro}>
        Hold the body constant, vary only the hook across variants, feed each
        variant's real retention back in, and let the server pick the
        retention-weighted winner.
      </Text>

      <View style={styles.row}>
        <TextInput
          value={keyInput}
          onChangeText={setKeyInput}
          placeholder="experiment key (e.g. launch_hooks_q3)"
          placeholderTextColor={colors.muted}
          autoCapitalize="none"
          autoCorrect={false}
          style={[styles.input, styles.flex1]}
          testID="exp-key-input"
        />
        <Pressable
          style={[styles.btn, busy === "load" && styles.btnDisabled]}
          disabled={busy === "load"}
          onPress={() => void load(keyInput)}
          accessibilityRole="button"
          testID="exp-load-btn"
        >
          <Text style={styles.btnText}>{busy === "load" ? "…" : "Load"}</Text>
        </Pressable>
      </View>

      {notice ? <Text style={styles.notice}>{notice}</Text> : null}
      {error ? <Text style={styles.errorText}>{error}</Text> : null}

      {phase === "loading" && !experiment ? (
        <View style={styles.state}>
          <ActivityIndicator color={colors.primary} />
          <Text style={styles.stateText}>Loading experiment…</Text>
        </View>
      ) : null}

      {experiment ? (
        <ExperimentView
          experiment={experiment}
          token={token}
          onEvaluate={() => void evaluate()}
          evaluating={busy === "evaluate"}
          onMetricsSaved={onMetricsSaved}
          onError={(m) => setError(m)}
        />
      ) : (
        <CreateForm
          keyValue={keyInput}
          bodyRef={bodyRef}
          onBodyRef={setBodyRef}
          hooksText={hooksText}
          onHooksText={setHooksText}
          hookCount={hookRefs.length}
          creating={busy === "create"}
          onCreate={() => void create()}
        />
      )}

      <View style={styles.spacer} />
    </ScrollView>
  );
}

interface CreateFormProps {
  keyValue: string;
  bodyRef: string;
  onBodyRef: (v: string) => void;
  hooksText: string;
  onHooksText: (v: string) => void;
  hookCount: number;
  creating: boolean;
  onCreate: () => void;
}

function CreateForm(props: CreateFormProps) {
  const {
    keyValue,
    bodyRef,
    onBodyRef,
    hooksText,
    onHooksText,
    hookCount,
    creating,
    onCreate,
  } = props;
  const canCreate =
    !creating &&
    keyValue.trim().length > 0 &&
    hookCount >= MIN_HOOKS &&
    hookCount <= MAX_HOOKS;

  return (
    <View style={styles.card}>
      <Text style={styles.cardTitle}>New experiment</Text>
      <Text style={styles.label}>Body ref (constant across variants)</Text>
      <TextInput
        value={bodyRef}
        onChangeText={onBodyRef}
        placeholder="optional — e.g. body_v2"
        placeholderTextColor={colors.muted}
        autoCapitalize="none"
        autoCorrect={false}
        style={styles.input}
        testID="exp-body-input"
      />
      <Text style={styles.label}>Hook variants — one per line</Text>
      <TextInput
        value={hooksText}
        onChangeText={onHooksText}
        placeholder={"POV you just...\nStop scrolling if...\nNobody tells you..."}
        placeholderTextColor={colors.muted}
        multiline
        style={[styles.input, styles.textarea]}
        testID="exp-hooks-input"
      />
      <Text style={styles.count}>
        {hookCount} hook{hookCount === 1 ? "" : "s"} · need {MIN_HOOKS}–{MAX_HOOKS}
      </Text>
      <Pressable
        style={[styles.btnWide, !canCreate && styles.btnDisabled]}
        disabled={!canCreate}
        onPress={onCreate}
        accessibilityRole="button"
        testID="exp-create-btn"
      >
        <Text style={styles.btnText}>
          {creating ? "Creating…" : "Create experiment"}
        </Text>
      </Pressable>
    </View>
  );
}

interface ExperimentViewProps {
  experiment: Experiment;
  token: string | undefined;
  onEvaluate: () => void;
  evaluating: boolean;
  onMetricsSaved: () => void;
  onError: (message: string) => void;
}

function ExperimentView(props: ExperimentViewProps) {
  const { experiment, token, onEvaluate, evaluating, onMetricsSaved, onError } =
    props;
  const decided = Boolean(experiment.winner_variant_id);

  return (
    <View>
      <View style={styles.card}>
        <View style={styles.cardHeader}>
          <Text style={styles.cardTitle}>{experiment.experiment_key}</Text>
          <View
            style={[
              styles.pill,
              { backgroundColor: decided ? colors.success : colors.cardAlt },
            ]}
          >
            <Text style={[styles.pillText, decided && { color: colors.bg }]}>
              {experiment.status}
            </Text>
          </View>
        </View>
        {experiment.body_ref ? (
          <Text style={styles.meta}>body: {experiment.body_ref}</Text>
        ) : null}
        {experiment.winner_hook_ref ? (
          <View style={styles.winnerBanner}>
            <Text style={styles.winnerText}>
              Winner · {experiment.winner_hook_ref}
            </Text>
          </View>
        ) : null}
        <Pressable
          style={[styles.btnWide, evaluating && styles.btnDisabled]}
          disabled={evaluating}
          onPress={onEvaluate}
          accessibilityRole="button"
          testID="exp-evaluate-btn"
        >
          <Text style={styles.btnText}>
            {evaluating ? "Evaluating…" : "Evaluate winner"}
          </Text>
        </Pressable>
      </View>

      <Text style={styles.sectionTitle}>
        Variants ({experiment.variants.length})
      </Text>
      {experiment.variants.map((v) => (
        <VariantRow
          key={v.id}
          experimentKey={experiment.experiment_key}
          variant={v}
          isWinner={v.id === experiment.winner_variant_id}
          token={token}
          onMetricsSaved={onMetricsSaved}
          onError={onError}
        />
      ))}
    </View>
  );
}

interface VariantRowProps {
  experimentKey: string;
  variant: ExperimentVariant;
  isWinner: boolean;
  token: string | undefined;
  onMetricsSaved: () => void;
  onError: (message: string) => void;
}

const METRIC_FIELDS: Array<{
  key: keyof MetricsBody;
  label: string;
  ratio: boolean;
  optional?: boolean;
}> = [
  { key: "views", label: "Views", ratio: false },
  { key: "completion_rate", label: "Completion", ratio: true, optional: true },
  { key: "avg_watch_frac", label: "Avg watch", ratio: true },
  { key: "rewatch_rate", label: "Rewatch", ratio: true, optional: true },
  { key: "engagement_rate", label: "Engagement", ratio: true },
];

function VariantRow(props: VariantRowProps) {
  const { experimentKey, variant, isWinner, token, onMetricsSaved, onError } =
    props;
  const [open, setOpen] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [form, setForm] = React.useState<Record<keyof MetricsBody, string>>({
    views: String(variant.views ?? 0),
    completion_rate:
      variant.completion_rate == null ? "" : String(variant.completion_rate),
    avg_watch_frac: String(variant.avg_watch_frac ?? 0),
    rewatch_rate: variant.rewatch_rate == null ? "" : String(variant.rewatch_rate),
    engagement_rate: String(variant.engagement_rate ?? 0),
  });

  const save = React.useCallback(async () => {
    const body: MetricsBody = {
      views: Math.max(0, Math.trunc(Number(form.views) || 0)),
      completion_rate: optionalRatio(form.completion_rate),
      avg_watch_frac: clamp01(Number(form.avg_watch_frac)),
      rewatch_rate: optionalRatio(form.rewatch_rate),
      engagement_rate: clamp01(Number(form.engagement_rate)),
    };
    setSaving(true);
    try {
      await ingestMetrics(experimentKey, variant.id, body, { token });
      setOpen(false);
      onMetricsSaved();
    } catch (err) {
      onError(
        err instanceof Error ? err.message : "Failed to save variant metrics.",
      );
    } finally {
      setSaving(false);
    }
  }, [form, experimentKey, variant.id, token, onMetricsSaved, onError]);

  return (
    <View style={[styles.variant, isWinner && styles.variantWinner]}>
      <View style={styles.cardHeader}>
        <Text style={styles.hookRef} numberOfLines={2}>
          {variant.hook_ref}
        </Text>
        {isWinner ? (
          <View style={[styles.pill, { backgroundColor: colors.success }]}>
            <Text style={[styles.pillText, { color: colors.bg }]}>winner</Text>
          </View>
        ) : null}
      </View>
      <View style={styles.metricsGrid}>
        <Metric label="Views" value={String(variant.views)} />
        <Metric label="Completion" value={measuredPct(variant.completion_rate)} />
        <Metric label="Avg watch" value={pct(variant.avg_watch_frac)} />
        <Metric label="Rewatch" value={measuredPct(variant.rewatch_rate)} />
        <Metric label="Engage" value={pct(variant.engagement_rate)} />
      </View>
      <Pressable
        onPress={() => setOpen((o) => !o)}
        accessibilityRole="button"
        testID={`variant-toggle-${variant.id}`}
      >
        <Text style={styles.linkText}>{open ? "Cancel" : "Log metrics"}</Text>
      </Pressable>

      {open ? (
        <View style={styles.metricsForm}>
          {METRIC_FIELDS.map((f) => (
            <View key={String(f.key)} style={styles.formField}>
              <Text style={styles.formLabel}>
                {f.label}
                {f.ratio ? " (0–1)" : ""}
                {f.optional ? ", blank if not reported" : ""}
              </Text>
              <TextInput
                value={form[f.key]}
                onChangeText={(t) =>
                  setForm((prev) => ({ ...prev, [f.key]: t }))
                }
                keyboardType="numeric"
                placeholder={f.optional ? "not measured" : undefined}
                placeholderTextColor={colors.muted}
                style={styles.formInput}
                testID={`metric-${String(f.key)}-${variant.id}`}
              />
            </View>
          ))}
          <Pressable
            style={[styles.btnWide, saving && styles.btnDisabled]}
            disabled={saving}
            onPress={() => void save()}
            accessibilityRole="button"
            testID={`metric-save-${variant.id}`}
          >
            <Text style={styles.btnText}>{saving ? "Saving…" : "Save metrics"}</Text>
          </Pressable>
        </View>
      ) : null}
    </View>
  );
}

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(1, value));
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.metric}>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={styles.metricValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16, paddingBottom: 40 },
  intro: { color: colors.textSecondary, fontSize: 14, lineHeight: 20, marginBottom: 16 },
  row: { flexDirection: "row", gap: 8, alignItems: "center" },
  flex1: { flex: 1 },
  input: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: colors.textPrimary,
    fontSize: 14,
  },
  textarea: { minHeight: 96, textAlignVertical: "top", marginBottom: 4 },
  btn: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingHorizontal: 18,
    paddingVertical: 11,
  },
  btnWide: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
    marginTop: 12,
  },
  btnDisabled: { opacity: 0.5 },
  btnText: { color: "#ffffff", fontWeight: "700", fontSize: 14 },
  notice: { color: colors.accent, fontSize: 13, marginTop: 12 },
  errorText: { color: colors.error, fontSize: 13, marginTop: 12 },
  state: { alignItems: "center", gap: 12, paddingVertical: 32 },
  stateText: { color: colors.textSecondary, fontSize: 14 },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginTop: 16,
  },
  cardTitle: { color: colors.textPrimary, fontSize: 16, fontWeight: "800" },
  cardHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 8,
  },
  label: { color: colors.muted, fontSize: 12, marginTop: 12, marginBottom: 6 },
  count: { color: colors.muted, fontSize: 12, marginTop: 6 },
  meta: { color: colors.textSecondary, fontSize: 13, marginTop: 6 },
  pill: { borderRadius: 999, paddingHorizontal: 10, paddingVertical: 3 },
  pillText: { color: colors.textSecondary, fontSize: 12, fontWeight: "700" },
  winnerBanner: {
    backgroundColor: colors.cardAlt,
    borderRadius: 10,
    padding: 10,
    marginTop: 10,
  },
  winnerText: { color: colors.success, fontSize: 14, fontWeight: "700" },
  sectionTitle: {
    color: colors.textPrimary,
    fontSize: 15,
    fontWeight: "800",
    marginTop: 20,
    marginBottom: 8,
  },
  variant: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 10,
  },
  variantWinner: { borderColor: colors.success },
  hookRef: { color: colors.textPrimary, fontSize: 14, fontWeight: "600", flex: 1 },
  metricsGrid: { flexDirection: "row", flexWrap: "wrap", gap: 10, marginTop: 12 },
  metric: { minWidth: 62 },
  metricLabel: { color: colors.muted, fontSize: 11 },
  metricValue: { color: colors.textPrimary, fontSize: 15, fontWeight: "700", marginTop: 2 },
  linkText: { color: colors.primary, fontSize: 13, fontWeight: "700", marginTop: 12 },
  metricsForm: { marginTop: 12, gap: 10 },
  formField: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  formLabel: { color: colors.textSecondary, fontSize: 13 },
  formInput: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 6,
    color: colors.textPrimary,
    fontSize: 14,
    minWidth: 110,
    textAlign: "right",
  },
  spacer: { height: 24 },
});
