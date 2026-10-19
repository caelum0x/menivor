/**
 * Studio · Caption Studio · Hook Score
 *
 * Nav manifest: { route: "/studio/captions/hook-score", title: "Hook Score" }
 *
 * Runs the REAL server hook predictor (POST /captions/hook-score) — unlike the
 * client-only hook-lab, this scores the six weighted first-3s signals on the
 * backend, returns the grade + gate verdict + per-signal subscores + weakness
 * reasons, and (when the hook misses the gate and an opening line is supplied)
 * concrete cold-open rewrite suggestions. The opening line is seeded from the
 * selected reel's hook via the `seed` route param. Explicit loading / error
 * states; nothing is persisted.
 */

import { useCallback, useState } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";

import { useLocalSearchParams } from "expo-router";

import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import {
  HOOK_SIGNALS,
  scoreHook,
  type HookScoreBody,
  type HookScoreResult,
  type HookSignalKey,
} from "@/lib/captions";
import { useSession } from "@/src/shared/auth";
import { clamp01 } from "@/components/captions/parse";
import {
  InlineError,
  KeyValueRow,
  Meter,
  PrimaryButton,
  SectionCard,
  Stepper,
  TagList,
  captionStyles,
} from "@/components/captions/ui";

const GATE = 0.7;

type SignalKey = HookSignalKey;

const INITIAL_SIGNALS: Record<SignalKey, number> = {
  motion: 0.9,
  text: 0.7,
  audio_onset: 0.8,
  early_cut: 0.6,
  speech: 0.7,
  face_or_subject: 0.6,
};

function gradeColor(grade: HookScoreResult["grade"]): string {
  if (grade === "viral" || grade === "strong") return colors.success;
  if (grade === "weak") return "#fbbf24";
  return colors.error;
}

export default function HookScoreScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const params = useLocalSearchParams<{ seed?: string }>();
  const seed = typeof params.seed === "string" ? params.seed : "";

  const [signals, setSignals] = useState<Record<SignalKey, number>>(INITIAL_SIGNALS);
  const [hookEnd, setHookEnd] = useState(3);
  const [openingLine, setOpeningLine] = useState(seed);
  const [result, setResult] = useState<HookScoreResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const step = useCallback((key: SignalKey, delta: number) => {
    setSignals((prev) => ({ ...prev, [key]: clamp01(prev[key] + delta) }));
  }, []);

  const run = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const body: HookScoreBody = {
        ...signals,
        hook_end_s: hookEnd,
        opening_line: openingLine.trim(),
      };
      const res = await scoreHook(body, { token });
      setResult(res);
    } catch (err) {
      setError(describeError(err, "Failed to score the hook."));
    } finally {
      setLoading(false);
    }
  }, [signals, hookEnd, openingLine, token]);

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
    >
      <Text style={styles.intro}>
        Score the first {hookEnd.toFixed(1)}s cold-open on the server. A reel must clear the{" "}
        {Math.round(GATE * 100)}% gate for viral-reach retention.
      </Text>

      <SectionCard title="First-3s signals" subtitle="Each 0..1, as the client probe would extract them.">
        {HOOK_SIGNALS.map(({ key, label, weight, hint }) => {
          const value = signals[key];
          return (
            <View key={key} style={styles.signalWrap}>
              <Stepper
                label={`${label}  ×${weight}`}
                meta={`+${(weight * value).toFixed(3)}`}
                value={value}
                fraction={value}
                onStep={(d) => step(key, d)}
                step={0.05}
              />
              <Text style={styles.hint}>{hint}</Text>
            </View>
          );
        })}
        <Stepper
          label="Hook window end (s)"
          meta={`${hookEnd.toFixed(1)}s`}
          value={hookEnd}
          fraction={hookEnd / 6}
          onStep={(d) => setHookEnd((v) => Math.max(0.5, Math.min(6, Math.round((v + d) * 10) / 10)))}
          step={0.5}
        />
      </SectionCard>

      <SectionCard
        title="Opening line"
        subtitle="Seeded from the selected reel. When the hook misses the gate, this drives rewrite suggestions."
      >
        <View style={captionStyles.field}>
          <Text style={styles.openingText}>
            {openingLine.trim() ? openingLine : "No opening line — suggestions are only returned below the gate."}
          </Text>
        </View>
      </SectionCard>

      <InlineError message={error} />

      <PrimaryButton label="Score hook" onPress={() => void run()} loading={loading} />

      {result ? (
        <View style={styles.resultWrap}>
          <SectionCard>
            <View style={styles.scoreRow}>
              <Text style={[styles.scoreValue, { color: gradeColor(result.grade) }]}>
                {Math.round(result.score * 100)}%
              </Text>
              <View style={[styles.gradePill, { backgroundColor: gradeColor(result.grade) }]}>
                <Text style={styles.gradePillText}>{result.grade}</Text>
              </View>
            </View>
            <Meter fraction={result.score} color={gradeColor(result.grade)} gate={GATE} />
            <Text style={styles.gateHint}>
              {result.passes_gate
                ? `Clears the ${Math.round(GATE * 100)}% gate.`
                : `Below the ${Math.round(GATE * 100)}% gate.`}
            </Text>
          </SectionCard>

          <SectionCard title="Subscores" subtitle="Weighted contribution per signal.">
            {Object.entries(result.subscores).map(([name, val]) => (
              <KeyValueRow key={name} label={name} value={val.toFixed(3)} />
            ))}
          </SectionCard>

          {result.reasons.length > 0 ? (
            <SectionCard title="Why it may fail">
              {result.reasons.map((r, i) => (
                <Text key={i} style={styles.reason}>
                  • {r}
                </Text>
              ))}
            </SectionCard>
          ) : null}

          {result.suggestions.length > 0 ? (
            <SectionCard title="Cold-open rewrites" subtitle="Strongest shape first.">
              {result.suggestions.map((s, i) => (
                <View key={i} style={styles.suggestion}>
                  <TagList tags={[s.shape]} tone="accent" />
                  <Text style={styles.suggestionText}>{s.text}</Text>
                  <Text style={styles.suggestionRationale}>{s.rationale}</Text>
                </View>
              ))}
            </SectionCard>
          ) : null}
        </View>
      ) : null}

      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  intro: { color: colors.textSecondary, fontSize: 14, lineHeight: 20, marginBottom: 14 },
  signalWrap: { gap: 2, marginBottom: 6 },
  hint: { color: colors.muted, fontSize: 11 },
  openingText: { color: colors.textPrimary, fontSize: 14, lineHeight: 20 },
  resultWrap: { marginTop: 16 },
  scoreRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  scoreValue: { fontSize: 40, fontWeight: "800" },
  gradePill: { borderRadius: 999, paddingHorizontal: 14, paddingVertical: 6 },
  gradePillText: { color: colors.bg, fontSize: 13, fontWeight: "800", textTransform: "uppercase" },
  gateHint: { color: colors.muted, fontSize: 12 },
  reason: { color: colors.textSecondary, fontSize: 13, lineHeight: 20 },
  suggestion: {
    gap: 4,
    paddingVertical: 8,
    borderBottomColor: colors.border,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  suggestionText: { color: colors.textPrimary, fontSize: 15, fontWeight: "600", lineHeight: 20 },
  suggestionRationale: { color: colors.muted, fontSize: 12, lineHeight: 18 },
  spacer: { height: 32 },
});
