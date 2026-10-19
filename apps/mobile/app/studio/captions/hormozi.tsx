/**
 * Studio · Caption Studio · Hormozi Captions
 *
 * Nav manifest: { route: "/studio/captions/hormozi", title: "Hormozi Captions" }
 *
 * Preview the Hormozi 1-2-word caption grouping (POST /captions/hormozi). The
 * script (seeded from the selected reel's hook) is tokenized into evenly word-
 * timed cues — standing in for the render pipeline's whisper timings — then sent
 * to the server, which returns the KaraokeStyle params and the accented cue
 * groups (with the highlighted key word per group). Form validation, explicit
 * loading / error / empty states.
 */

import { useCallback, useMemo, useState } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";

import { useLocalSearchParams } from "expo-router";

import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import {
  hormoziGroups,
  type HormoziBody,
  type HormoziResult,
} from "@/lib/captions";
import { tokenizeScript, wordCount } from "@/components/captions/parse";
import { useSession } from "@/src/shared/auth";
import {
  Chips,
  InlineError,
  KeyValueRow,
  LabeledInput,
  PrimaryButton,
  SectionCard,
  Stepper,
} from "@/components/captions/ui";

const MAX_PER_GROUP_MIN = 1;
const MAX_PER_GROUP_MAX = 4;

const HIGHLIGHTS: ReadonlyArray<{ id: string; label: string }> = [
  { id: "#FFD93D", label: "Gold" },
  { id: "#22c55e", label: "Green" },
  { id: "#ef4444", label: "Red" },
  { id: "#3b82f6", label: "Blue" },
];

export default function HormoziScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const params = useLocalSearchParams<{ seed?: string }>();
  const seed = typeof params.seed === "string" ? params.seed : "";

  const [script, setScript] = useState(seed);
  const [maxPerGroup, setMaxPerGroup] = useState(2);
  const [highlight, setHighlight] = useState<string>(HIGHLIGHTS[0].id);
  const [duration, setDuration] = useState(8);
  const [result, setResult] = useState<HormoziResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const words = useMemo(() => wordCount(script), [script]);
  const canSubmit = words > 0;

  const run = useCallback(async () => {
    if (!canSubmit) {
      setError("Enter a script line to group.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const body: HormoziBody = {
        words: tokenizeScript(script, duration),
        max_per_group: maxPerGroup,
        highlight_hex: highlight,
      };
      const res = await hormoziGroups(body, { token });
      setResult(res);
    } catch (err) {
      setError(describeError(err, "Failed to group the captions."));
    } finally {
      setLoading(false);
    }
  }, [canSubmit, script, duration, maxPerGroup, highlight, token]);

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
    >
      <Text style={styles.intro}>
        Preview how a script chunks into accented 1-2 word cues. Timings are spread evenly
        across the target duration to stand in for whisper word timings.
      </Text>

      <SectionCard>
        <LabeledInput
          label="Script"
          value={script}
          onChangeText={setScript}
          placeholder="Stop scrolling — this is the fastest way to edit reels"
          multiline
          helper={`${words} ${words === 1 ? "word" : "words"}`}
        />
        <Stepper
          label="Target duration (s)"
          meta={`${duration}s`}
          value={duration}
          fraction={duration / 30}
          onStep={(d) => setDuration((v) => Math.max(1, Math.min(30, v + d)))}
          step={1}
        />
        <Stepper
          label="Max words per group"
          meta={`${maxPerGroup}`}
          value={maxPerGroup}
          fraction={maxPerGroup / MAX_PER_GROUP_MAX}
          onStep={(d) =>
            setMaxPerGroup((v) =>
              Math.max(MAX_PER_GROUP_MIN, Math.min(MAX_PER_GROUP_MAX, v + d)),
            )
          }
          step={1}
        />
        <Text style={styles.fieldLabel}>Highlight color</Text>
        <Chips options={HIGHLIGHTS} selected={highlight} onSelect={setHighlight} />
      </SectionCard>

      <InlineError message={error} />

      <PrimaryButton
        label="Group captions"
        onPress={() => void run()}
        loading={loading}
        disabled={!canSubmit}
      />

      {result ? (
        <View style={styles.resultWrap}>
          <SectionCard title="Style params" subtitle="KaraokeStyle fed to the ASS builder.">
            <KeyValueRow label="Font" value={result.style.font} />
            <KeyValueRow label="All caps" value={result.style.all_caps ? "yes" : "no"} />
            <KeyValueRow label="Highlight" value={result.style.highlight_hex} />
            <KeyValueRow label="Base" value={result.style.base_hex} />
            <KeyValueRow label="Outline / shadow" value={`${result.style.outline} / ${result.style.shadow}`} />
          </SectionCard>

          <SectionCard title={`Cues (${result.groups.length})`}>
            {result.groups.length === 0 ? (
              <Text style={styles.empty}>No cues were produced from this script.</Text>
            ) : (
              result.groups.map((g, gi) => (
                <View key={gi} style={styles.cueRow}>
                  <View style={styles.cueWords}>
                    {g.words.map((w, wi) => {
                      const isHi = wi === g.highlight_index;
                      return (
                        <Text
                          key={wi}
                          style={[
                            styles.cueWord,
                            isHi ? { color: result.style.highlight_hex } : null,
                          ]}
                        >
                          {result.style.all_caps ? w.toUpperCase() : w}
                        </Text>
                      );
                    })}
                  </View>
                  <Text style={styles.cueTime}>
                    {g.start.toFixed(2)}s – {g.end.toFixed(2)}s
                  </Text>
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
  fieldLabel: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  resultWrap: { marginTop: 16 },
  cueRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 8,
    borderBottomColor: colors.border,
    borderBottomWidth: StyleSheet.hairlineWidth,
    gap: 12,
  },
  cueWords: { flexDirection: "row", flexWrap: "wrap", gap: 6, flex: 1 },
  cueWord: { color: colors.textPrimary, fontSize: 16, fontWeight: "800" },
  cueTime: { color: colors.muted, fontSize: 12 },
  empty: { color: colors.muted, fontSize: 13 },
  spacer: { height: 32 },
});
