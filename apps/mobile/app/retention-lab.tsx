/**
 * Retention Lab (mobile) — pick or edit a per-second viewer curve and see how the
 * pipeline reads it: reach tier + boost multiplier and the drop-off analysis
 * (biggest single-second cliff + first-3s average). All from the real
 * `@reelforge/growth-analytics` retention model (byte-identical to `retention.py`).
 * Mirrors the web `/retention-lab`. Pure client-side reference; nothing is submitted.
 */

import * as React from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { dropoff, normalizeCurve, reachTier } from "@reelforge/growth-analytics";

import { colors } from "@/components/me/theme";

const PRESETS: Array<{ label: string; samples: number[] }> = [
  { label: "Viral", samples: [1000, 980, 960, 950, 945, 940, 935, 930, 925, 920] },
  { label: "Steep cliff", samples: [1000, 940, 500, 460, 440, 430, 420, 410, 405, 400] },
  { label: "Slow bleed", samples: [1000, 900, 820, 740, 660, 590, 520, 460, 410, 370] },
];

function parseSamples(text: string): number[] {
  return text
    .split(/[,\s]+/)
    .map((t) => Number(t.trim()))
    .filter((n) => Number.isFinite(n) && n >= 0);
}

/** Tiny inline sparkline from a normalized curve (0..1), drawn with flex bars. */
function Sparkline({ curve, tint }: { curve: number[]; tint: string }) {
  return (
    <View style={styles.spark}>
      {curve.map((v, i) => (
        <View key={i} style={[styles.sparkBar, { height: `${Math.max(2, v * 100)}%`, backgroundColor: tint }]} />
      ))}
    </View>
  );
}

export default function RetentionLabScreen() {
  const [text, setText] = React.useState(PRESETS[0]!.samples.join(", "));
  const samples = React.useMemo(() => parseSamples(text), [text]);

  const { curve, tier, drop, avg } = React.useMemo(() => {
    const curve = normalizeCurve(samples);
    const avg = curve.length ? curve.reduce((a, b) => a + b, 0) / curve.length : 0;
    return { curve, tier: reachTier(avg), drop: dropoff(curve), avg };
  }, [samples]);

  const tint = tier.tier === "viral" ? colors.success : tier.tier === "boosted" ? colors.accent : "#fbbf24";

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.intro}>
        Paste a per-second viewer curve; the reach tier + drop-off come from the real
        growth-analytics model the pipeline scores with.
      </Text>

      <View style={styles.presetRow}>
        {PRESETS.map((p) => (
          <Pressable key={p.label} style={styles.presetBtn} onPress={() => setText(p.samples.join(", "))}>
            <Text style={styles.presetText}>{p.label}</Text>
          </Pressable>
        ))}
      </View>

      <TextInput
        value={text}
        onChangeText={setText}
        multiline
        placeholder="1000, 940, 720, …"
        placeholderTextColor={colors.muted}
        style={styles.input}
      />
      <Text style={styles.count}>{samples.length} samples (comma or space separated)</Text>

      {samples.length >= 2 ? (
        <>
          <View style={styles.card}>
            <View style={styles.cardHeader}>
              <Text style={styles.cardLabel}>Normalized retention</Text>
              <View style={[styles.pill, { backgroundColor: tint }]}>
                <Text style={styles.pillText}>
                  {tier.tier} · {tier.multiplier}× reach
                </Text>
              </View>
            </View>
            <Sparkline curve={curve} tint={tint} />
          </View>

          <View style={styles.stats}>
            <Stat label="Avg" value={`${Math.round(avg * 100)}%`} accent />
            <Stat label="First 3s" value={`${Math.round(drop.first_3s * 100)}%`} />
            <Stat label="Max drop" value={`${Math.round(drop.max_drop * 100)}% @${drop.max_drop_at}s`} />
          </View>
        </>
      ) : (
        <View style={styles.card}>
          <Text style={styles.empty}>Enter at least two samples to analyze.</Text>
        </View>
      )}

      <View style={styles.spacer} />
    </ScrollView>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statLabel}>{label}</Text>
      <Text style={[styles.statValue, accent && { color: colors.accent }]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  intro: { color: colors.textSecondary, fontSize: 14, marginBottom: 16 },
  presetRow: { flexDirection: "row", gap: 8, marginBottom: 10, flexWrap: "wrap" },
  presetBtn: { backgroundColor: colors.cardAlt, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 8 },
  presetText: { color: colors.textPrimary, fontSize: 13, fontWeight: "600" },
  input: {
    backgroundColor: colors.cardAlt, borderColor: colors.border, borderWidth: 1, borderRadius: 10,
    padding: 12, color: colors.textPrimary, fontSize: 13, minHeight: 60, textAlignVertical: "top",
  },
  count: { color: colors.muted, fontSize: 12, marginTop: 6, marginBottom: 16 },
  card: {
    backgroundColor: colors.card, borderColor: colors.border, borderWidth: 1,
    borderRadius: 12, padding: 12, marginBottom: 12,
  },
  cardHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 12 },
  cardLabel: { color: colors.muted, fontSize: 13 },
  pill: { borderRadius: 999, paddingHorizontal: 10, paddingVertical: 3 },
  pillText: { color: colors.bg, fontSize: 12, fontWeight: "700" },
  spark: { flexDirection: "row", alignItems: "flex-end", gap: 3, height: 96 },
  sparkBar: { flex: 1, borderTopLeftRadius: 2, borderTopRightRadius: 2, minHeight: 2 },
  stats: { flexDirection: "row", gap: 10 },
  stat: {
    flex: 1, backgroundColor: colors.card, borderColor: colors.border, borderWidth: 1,
    borderRadius: 12, padding: 12,
  },
  statLabel: { color: colors.muted, fontSize: 12 },
  statValue: { color: colors.textPrimary, fontSize: 16, fontWeight: "700", marginTop: 4 },
  empty: { color: colors.muted, fontSize: 13 },
  spacer: { height: 24 },
});
