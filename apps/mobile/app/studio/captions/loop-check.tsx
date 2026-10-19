/**
 * Studio · Caption Studio · Loop Check
 *
 * Nav manifest: { route: "/studio/captions/loop-check", title: "Loop Check" }
 *
 * Find the frame that loops back to the start most seamlessly (POST
 * /captions/loop-check) for ASMR / loop genres. Paste per-candidate-frame
 * discontinuity scores (0 identical .. 1 hard seam), set fps and the loop
 * duration window, and the server returns the best cut frame + whether it was
 * accepted. Input parsing with a soft warning for skipped tokens, a "sample"
 * generator, form validation and explicit loading / error states.
 */

import { useCallback, useMemo, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import {
  checkLoop,
  type LoopCheckBody,
  type LoopCheckResult,
} from "@/lib/captions";
import { parseNumberList } from "@/components/captions/parse";
import { useSession } from "@/src/shared/auth";
import {
  InlineError,
  KeyValueRow,
  LabeledInput,
  PrimaryButton,
  SectionCard,
  Stepper,
} from "@/components/captions/ui";

/** A smooth-ish discontinuity curve with a clear seamless dip, for a demo run. */
function sampleDiscontinuities(n: number): number[] {
  return Array.from({ length: n }, (_, i) => {
    const base = 0.3 + 0.25 * Math.sin((i / n) * Math.PI * 4);
    const dip = i === Math.floor(n * 0.6) ? 0.02 : base;
    return Number(Math.max(0, Math.min(1, dip)).toFixed(3));
  });
}

export default function LoopCheckScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const [raw, setRaw] = useState("");
  const [fps, setFps] = useState(30);
  const [minS, setMinS] = useState(1);
  const [result, setResult] = useState<LoopCheckResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const parsed = useMemo(() => parseNumberList(raw), [raw]);
  const canSubmit = parsed.values.length > 0;

  const fillSample = useCallback(() => {
    setRaw(sampleDiscontinuities(90).join(", "));
    setResult(null);
    setError("");
  }, []);

  const run = useCallback(async () => {
    if (!canSubmit) {
      setError("Enter at least one discontinuity score.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const body: LoopCheckBody = {
        discontinuities: parsed.values,
        fps,
        min_s: minS,
      };
      const res = await checkLoop(body, { token });
      setResult(res);
    } catch (err) {
      setError(describeError(err, "Failed to check the loop."));
    } finally {
      setLoading(false);
    }
  }, [canSubmit, parsed.values, fps, minS, token]);

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
    >
      <Text style={styles.intro}>
        Given per-frame discontinuity scores, pick the frame that loops back to the start most
        seamlessly. 0 = identical to the first frame, 1 = a hard seam.
      </Text>

      <SectionCard>
        <LabeledInput
          label="Discontinuities"
          value={raw}
          onChangeText={setRaw}
          placeholder="0.3, 0.28, 0.12, 0.02, …"
          multiline
          keyboardType="decimal-pad"
          helper={
            parsed.skipped > 0
              ? `${parsed.values.length} values · ${parsed.skipped} skipped (not a number)`
              : `${parsed.values.length} values`
          }
        />
        <Pressable style={styles.sampleBtn} onPress={fillSample} accessibilityRole="button">
          <Text style={styles.sampleBtnText}>Fill with a sample curve</Text>
        </Pressable>
        <Stepper
          label="Frame rate (fps)"
          meta={`${fps}`}
          value={fps}
          fraction={fps / 60}
          onStep={(d) => setFps((v) => Math.max(1, Math.min(60, v + d)))}
          step={1}
        />
        <Stepper
          label="Min loop length (s)"
          meta={`${minS.toFixed(1)}s`}
          value={minS}
          fraction={minS / 10}
          onStep={(d) => setMinS((v) => Math.max(0, Math.min(10, Math.round((v + d) * 10) / 10)))}
          step={0.5}
        />
      </SectionCard>

      <InlineError message={error} />

      <PrimaryButton
        label="Find loop point"
        onPress={() => void run()}
        loading={loading}
        disabled={!canSubmit}
      />

      {result ? (
        <View style={styles.resultWrap}>
          <SectionCard>
            <View style={styles.verdictRow}>
              <View
                style={[
                  styles.verdictPill,
                  { backgroundColor: result.accepted ? colors.success : colors.error },
                ]}
              >
                <Text style={styles.verdictText}>
                  {result.accepted ? "seamless loop" : "no clean loop"}
                </Text>
              </View>
            </View>
            <KeyValueRow label="End frame" value={String(result.end_frame)} strong />
            <KeyValueRow label="End time" value={`${result.end_s.toFixed(3)}s`} />
            <KeyValueRow label="Discontinuity" value={result.discontinuity.toFixed(4)} />
            <KeyValueRow label="Reason" value={result.reason} />
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
  verdictRow: { flexDirection: "row", marginBottom: 4 },
  verdictPill: { borderRadius: 999, paddingHorizontal: 14, paddingVertical: 6 },
  verdictText: { color: colors.bg, fontSize: 13, fontWeight: "800" },
  spacer: { height: 32 },
});
