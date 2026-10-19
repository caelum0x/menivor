/**
 * Studio · Caption Studio · Beat Fit
 *
 * Nav manifest: { route: "/studio/captions/beat-fit", title: "Beat Fit" }
 *
 * Preview beat-cut nudge fits (POST /captions/beat-fit): given your cut times
 * and the track's beat times, the server ranks the -2 / -3 / -4 frame nudges by
 * mean snap error (lower is tighter). The tightest option is highlighted as the
 * recommended nudge. Input parsing with soft skip warnings, a sample generator,
 * form validation and explicit loading / error states.
 */

import { useCallback, useMemo, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import { beatFit, type BeatFitBody, type BeatFitResult } from "@/lib/captions";
import { parseNumberList } from "@/components/captions/parse";
import { useSession } from "@/src/shared/auth";
import {
  InlineError,
  LabeledInput,
  PrimaryButton,
  SectionCard,
  Stepper,
} from "@/components/captions/ui";

function sampleBeats(count: number, bpm: number): number[] {
  const period = 60 / bpm;
  return Array.from({ length: count }, (_, i) => Number((i * period).toFixed(3)));
}

/** Cuts drifting slightly off the beat grid, so a nudge has something to fix. */
function sampleCuts(beats: number[]): number[] {
  return beats
    .filter((_, i) => i % 2 === 0)
    .map((b, i) => Number((b + 0.05 + i * 0.01).toFixed(3)));
}

interface RankedFit {
  nudge: string;
  error: number;
  best: boolean;
}

function rankFits(fits: Record<string, number>): RankedFit[] {
  const entries = Object.entries(fits);
  if (entries.length === 0) return [];
  const min = Math.min(...entries.map(([, v]) => v));
  return entries
    .map(([nudge, error]) => ({ nudge, error, best: error === min }))
    .sort((a, b) => a.error - b.error);
}

export default function BeatFitScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const [cutsRaw, setCutsRaw] = useState("");
  const [beatsRaw, setBeatsRaw] = useState("");
  const [fps, setFps] = useState(30);
  const [result, setResult] = useState<BeatFitResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const cuts = useMemo(() => parseNumberList(cutsRaw), [cutsRaw]);
  const beats = useMemo(() => parseNumberList(beatsRaw), [beatsRaw]);
  const canSubmit = cuts.values.length > 0 && beats.values.length > 0;

  const ranked = useMemo(() => (result ? rankFits(result.fits) : []), [result]);

  const fillSample = useCallback(() => {
    const b = sampleBeats(16, 120);
    setBeatsRaw(b.join(", "));
    setCutsRaw(sampleCuts(b).join(", "));
    setResult(null);
    setError("");
  }, []);

  const run = useCallback(async () => {
    if (!canSubmit) {
      setError("Enter both cut times and beat times.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const body: BeatFitBody = { cuts: cuts.values, beats: beats.values, fps };
      const res = await beatFit(body, { token });
      setResult(res);
    } catch (err) {
      setError(describeError(err, "Failed to compute beat fits."));
    } finally {
      setLoading(false);
    }
  }, [canSubmit, cuts.values, beats.values, fps, token]);

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
    >
      <Text style={styles.intro}>
        Rank frame nudges by how tightly your cuts snap to the music beats. Lower mean error is a
        tighter fit; the best option is the recommended nudge.
      </Text>

      <SectionCard>
        <LabeledInput
          label="Cut times (s)"
          value={cutsRaw}
          onChangeText={setCutsRaw}
          placeholder="0.55, 1.05, 1.55, …"
          multiline
          keyboardType="decimal-pad"
          helper={
            cuts.skipped > 0
              ? `${cuts.values.length} cuts · ${cuts.skipped} skipped`
              : `${cuts.values.length} cuts`
          }
        />
        <LabeledInput
          label="Beat times (s)"
          value={beatsRaw}
          onChangeText={setBeatsRaw}
          placeholder="0.5, 1.0, 1.5, …"
          multiline
          keyboardType="decimal-pad"
          helper={
            beats.skipped > 0
              ? `${beats.values.length} beats · ${beats.skipped} skipped`
              : `${beats.values.length} beats`
          }
        />
        <Pressable style={styles.sampleBtn} onPress={fillSample} accessibilityRole="button">
          <Text style={styles.sampleBtnText}>Fill with a 120 BPM sample</Text>
        </Pressable>
        <Stepper
          label="Frame rate (fps)"
          meta={`${fps}`}
          value={fps}
          fraction={fps / 60}
          onStep={(d) => setFps((v) => Math.max(1, Math.min(60, v + d)))}
          step={1}
        />
      </SectionCard>

      <InlineError message={error} />

      <PrimaryButton
        label="Rank nudges"
        onPress={() => void run()}
        loading={loading}
        disabled={!canSubmit}
      />

      {result ? (
        <View style={styles.resultWrap}>
          <SectionCard title="Nudge fits" subtitle="Mean snap error in seconds — lower is tighter.">
            {ranked.length === 0 ? (
              <Text style={styles.empty}>No fits returned.</Text>
            ) : (
              ranked.map((r) => (
                <View
                  key={r.nudge}
                  style={[styles.fitRow, r.best ? styles.fitRowBest : null]}
                >
                  <View style={styles.fitLeft}>
                    <Text style={styles.fitNudge}>-{r.nudge} frames</Text>
                    {r.best ? (
                      <View style={styles.bestPill}>
                        <Text style={styles.bestPillText}>best</Text>
                      </View>
                    ) : null}
                  </View>
                  <Text style={styles.fitError}>{r.error.toFixed(4)}s</Text>
                </View>
              ))
            )}
          </SectionCard>
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
  sampleBtn: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 10,
    alignItems: "center",
  },
  sampleBtnText: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  resultWrap: { marginTop: 16 },
  fitRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 12,
    paddingHorizontal: 12,
    borderRadius: 10,
    backgroundColor: colors.cardAlt,
    marginBottom: 8,
  },
  fitRowBest: { borderColor: colors.primary, borderWidth: 1 },
  fitLeft: { flexDirection: "row", alignItems: "center", gap: 10 },
  fitNudge: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  bestPill: {
    backgroundColor: colors.primary,
    borderRadius: 999,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  bestPillText: { color: colors.bg, fontSize: 10, fontWeight: "800", textTransform: "uppercase" },
  fitError: { color: colors.textSecondary, fontSize: 14, fontWeight: "600" },
  empty: { color: colors.muted, fontSize: 13 },
  spacer: { height: 32 },
});
