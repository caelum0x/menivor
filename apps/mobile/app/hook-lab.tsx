/**
 * Hook Score Lab (mobile) — an interactive tool over the real
 * `@reelforge/growth-analytics.hookScore`, the same weighted first-3s model
 * (byte-identical to `hook.py`) the pipeline gates on. Adjust the four signals
 * and watch the score + the 70% gate update live. Pure client-side reference;
 * nothing is submitted. Mirrors the web `/hook-lab` screen.
 */

import * as React from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { GATE, hookScore, type HookSignals } from "@reelforge/growth-analytics";

import { colors } from "@/components/me/theme";
import { Icon } from "@/components/ui/Icon";

// Mirrors the private WEIGHTS in growth-analytics/hook.ts (stable constants),
// used only to visualize each signal's contribution; the score comes from the
// package's hookScore, never recomputed here.
const WEIGHTS: Array<{ key: keyof HookSignals; label: string; weight: number }> = [
  { key: "motion", label: "Motion", weight: 0.35 },
  { key: "audio_onset", label: "Audio onset", weight: 0.25 },
  { key: "contrast", label: "Contrast", weight: 0.2 },
  { key: "text", label: "Text", weight: 0.2 },
];

function clamp01(v: number): number {
  return Math.max(0, Math.min(1, Math.round(v * 100) / 100));
}

export default function HookLabScreen() {
  const [signals, setSignals] = React.useState<Required<HookSignals>>({
    motion: 0.9,
    contrast: 0.8,
    text: 0.7,
    audio_onset: 0.8,
  });

  const result = React.useMemo(() => hookScore(signals), [signals]);
  const set = (key: keyof HookSignals, delta: number) =>
    setSignals((prev) => ({ ...prev, [key]: clamp01((prev[key] ?? 0) + delta) }));

  const scorePct = Math.round(result.score * 100);
  const scoreColor = result.passes ? colors.success : colors.error;

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.intro}>
        The weighted first-3s hook model the pipeline gates on — identical to the renderer via
        growth-analytics. A reel must clear the {Math.round(GATE * 100)}% gate.
      </Text>

      <View style={styles.scoreCard}>
        <Text style={[styles.scoreValue, { color: scoreColor }]}>{scorePct}%</Text>
        <View style={[styles.pill, { backgroundColor: result.passes ? colors.success : colors.error }]}>
          <Text style={styles.pillText}>{result.passes ? "clears gate" : "below gate"}</Text>
        </View>
        <View style={styles.track}>
          <View style={[styles.gateMark, { left: `${GATE * 100}%` }]} />
          <View style={[styles.fill, { width: `${Math.min(100, scorePct)}%`, backgroundColor: scoreColor }]} />
        </View>
        <Text style={styles.gateHint}>The marker is the {Math.round(GATE * 100)}% gate.</Text>
      </View>

      {WEIGHTS.map(({ key, label, weight }) => {
        const value = signals[key] ?? 0;
        const contribution = weight * value;
        return (
          <View key={key} style={styles.signal}>
            <View style={styles.signalHeader}>
              <Text style={styles.signalLabel}>
                {label} <Text style={styles.weight}>×{weight}</Text>
              </Text>
              <Text style={styles.signalMeta}>
                {value.toFixed(2)} → +{contribution.toFixed(3)}
              </Text>
            </View>
            <View style={styles.controls}>
              <Pressable style={styles.stepBtn} onPress={() => set(key, -0.05)}>
                <Icon name="remove" style={styles.stepBtnText} />
              </Pressable>
              <View style={styles.valueTrack}>
                <View style={[styles.valueFill, { width: `${value * 100}%` }]} />
              </View>
              <Pressable style={styles.stepBtn} onPress={() => set(key, 0.05)}>
                <Icon name="add" style={styles.stepBtnText} />
              </Pressable>
            </View>
          </View>
        );
      })}

      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  intro: { color: colors.textSecondary, fontSize: 14, marginBottom: 16 },
  scoreCard: {
    backgroundColor: colors.card, borderColor: colors.border, borderWidth: 1,
    borderRadius: 12, padding: 16, alignItems: "center", marginBottom: 16,
  },
  scoreValue: { fontSize: 44, fontWeight: "800" },
  pill: { borderRadius: 999, paddingHorizontal: 12, paddingVertical: 4, marginTop: 4 },
  pillText: { color: colors.bg, fontSize: 12, fontWeight: "700" },
  track: {
    width: "100%", height: 8, borderRadius: 4, backgroundColor: colors.cardAlt,
    marginTop: 16, position: "relative", overflow: "hidden",
  },
  gateMark: { position: "absolute", top: 0, bottom: 0, width: 2, backgroundColor: "#fbbf24" },
  fill: { height: "100%", borderRadius: 4 },
  gateHint: { color: colors.muted, fontSize: 12, marginTop: 6 },
  signal: {
    backgroundColor: colors.card, borderColor: colors.border, borderWidth: 1,
    borderRadius: 12, padding: 12, marginBottom: 10,
  },
  signalHeader: { flexDirection: "row", justifyContent: "space-between", marginBottom: 10 },
  signalLabel: { color: colors.textPrimary, fontSize: 14, fontWeight: "600" },
  weight: { color: colors.muted, fontSize: 12 },
  signalMeta: { color: colors.muted, fontSize: 12 },
  controls: { flexDirection: "row", alignItems: "center", gap: 12 },
  stepBtn: {
    width: 36, height: 36, borderRadius: 10, backgroundColor: colors.cardAlt,
    alignItems: "center", justifyContent: "center",
  },
  stepBtnText: { color: colors.textPrimary, fontSize: 20, fontWeight: "700" },
  valueTrack: { flex: 1, height: 8, borderRadius: 4, backgroundColor: colors.cardAlt, overflow: "hidden" },
  valueFill: { height: "100%", backgroundColor: colors.primary },
  spacer: { height: 24 },
});
