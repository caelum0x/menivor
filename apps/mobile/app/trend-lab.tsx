/**
 * Trend Lab (mobile) — paste a sound's daily-usage series and read the pipeline's
 * trend signals: saturation, velocity, decay, and the headline **opportunity**
 * score (build-to-it-before-it-peaks), plus the cross-platform ad-safe rule. All
 * from the real `@reelforge/trends-schema` scoring (bit-identical to `scoring.py`).
 * Mirrors the web `/trend-lab`. Pure client-side reference; nothing is submitted.
 */

import * as React from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { adSafe, score } from "@reelforge/trends-schema";

import { colors } from "@/components/me/theme";

const PRESETS: Array<{ label: string; series: number[] }> = [
  { label: "Rising", series: [10, 18, 30, 55, 95, 160, 250] },
  { label: "Peaked", series: [40, 120, 300, 520, 610, 605, 600] },
  { label: "Saturated", series: [500, 700, 850, 900, 905, 900, 895] },
  { label: "Fading", series: [900, 820, 640, 470, 330, 220, 140] },
];

function parseSeries(text: string): number[] {
  return text
    .split(/[,\s]+/)
    .map((t) => Number(t.trim()))
    .filter((n) => Number.isFinite(n) && n >= 0);
}

function Sparkline({ series }: { series: number[] }) {
  const peak = Math.max(...series, 1);
  return (
    <View style={styles.spark}>
      {series.map((v, i) => (
        <View
          key={i}
          style={[
            styles.sparkBar,
            { height: `${Math.max(2, (v / peak) * 100)}%`, backgroundColor: i === series.length - 1 ? colors.primary : colors.accent },
          ]}
        />
      ))}
    </View>
  );
}

export default function TrendLabScreen() {
  const [text, setText] = React.useState(PRESETS[0]!.series.join(", "));
  const [licensed, setLicensed] = React.useState(true);
  const [explicit, setExplicit] = React.useState(false);
  const series = React.useMemo(() => parseSeries(text), [text]);
  const s = React.useMemo(() => (series.length >= 2 ? score(series) : null), [series]);
  const safe = adSafe({ licensed, explicit });

  const oppColor = (o: number) => (o >= 0.66 ? colors.success : o >= 0.4 ? colors.accent : "#fbbf24");

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.intro}>
        Paste a sound's daily-usage series; the signals come from the real trends-schema scoring the
        pipeline ranks rising audio with.
      </Text>

      <View style={styles.presetRow}>
        {PRESETS.map((p) => (
          <Pressable key={p.label} style={styles.presetBtn} onPress={() => setText(p.series.join(", "))}>
            <Text style={styles.presetText}>{p.label}</Text>
          </Pressable>
        ))}
      </View>

      <TextInput
        value={text}
        onChangeText={setText}
        multiline
        placeholder="10, 18, 30, …"
        placeholderTextColor={colors.muted}
        style={styles.input}
      />
      <Text style={styles.count}>{series.length} data points</Text>
      {series.length >= 2 ? (
        <View style={styles.card}>
          <Sparkline series={series} />
        </View>
      ) : null}

      {s ? (
        <View style={styles.statGrid}>
          <Stat label="Opportunity" value={`${Math.round(s.opportunity * 100)}%`} color={oppColor(s.opportunity)} />
          <Stat label="Velocity" value={s.velocity.toFixed(3)} />
          <Stat label="Saturation" value={`${Math.round(s.saturation * 100)}%`} />
          <Stat label="Decay" value={`${Math.round(s.decay * 100)}%`} />
        </View>
      ) : (
        <View style={styles.card}>
          <Text style={styles.empty}>Enter at least two data points.</Text>
        </View>
      )}

      <View style={styles.card}>
        <View style={styles.adHeader}>
          <Text style={styles.adTitle}>Ad-safe check</Text>
          <View style={[styles.pill, { backgroundColor: safe ? colors.success : colors.error }]}>
            <Text style={styles.pillText}>{safe ? "ad-safe" : "not ad-safe"}</Text>
          </View>
        </View>
        <View style={styles.toggleRow}>
          <Pressable style={[styles.toggle, licensed && styles.toggleOn]} onPress={() => setLicensed((v) => !v)}>
            <Text style={[styles.toggleText, licensed && styles.toggleTextOn]}>Licensed</Text>
          </Pressable>
          <Pressable style={[styles.toggle, explicit && styles.toggleDanger]} onPress={() => setExplicit((v) => !v)}>
            <Text style={[styles.toggleText, explicit && styles.toggleTextOn]}>Explicit</Text>
          </Pressable>
        </View>
        <Text style={styles.adHint}>Cross-platform (Meta-compatible) rule: licensed and not explicit.</Text>
      </View>

      <View style={styles.spacer} />
    </ScrollView>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statLabel}>{label}</Text>
      <Text style={[styles.statValue, color ? { color } : null]}>{value}</Text>
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
    padding: 12, color: colors.textPrimary, fontSize: 13, minHeight: 56, textAlignVertical: "top",
  },
  count: { color: colors.muted, fontSize: 12, marginTop: 6, marginBottom: 12 },
  card: {
    backgroundColor: colors.card, borderColor: colors.border, borderWidth: 1,
    borderRadius: 12, padding: 12, marginBottom: 12,
  },
  spark: { flexDirection: "row", alignItems: "flex-end", gap: 3, height: 70 },
  sparkBar: { flex: 1, borderTopLeftRadius: 2, borderTopRightRadius: 2, minHeight: 2 },
  statGrid: { flexDirection: "row", flexWrap: "wrap", gap: 10, marginBottom: 12 },
  stat: {
    flexBasis: "47%", flexGrow: 1, backgroundColor: colors.card, borderColor: colors.border, borderWidth: 1,
    borderRadius: 12, padding: 12,
  },
  statLabel: { color: colors.muted, fontSize: 12 },
  statValue: { color: colors.textPrimary, fontSize: 18, fontWeight: "700", marginTop: 4 },
  empty: { color: colors.muted, fontSize: 13 },
  adHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 12 },
  adTitle: { color: colors.textPrimary, fontSize: 14, fontWeight: "600" },
  pill: { borderRadius: 999, paddingHorizontal: 10, paddingVertical: 3 },
  pillText: { color: colors.bg, fontSize: 12, fontWeight: "700" },
  toggleRow: { flexDirection: "row", gap: 8 },
  toggle: {
    flex: 1, borderRadius: 10, paddingVertical: 10, alignItems: "center",
    backgroundColor: colors.cardAlt, borderColor: colors.border, borderWidth: 1,
  },
  toggleOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  toggleDanger: { backgroundColor: colors.error, borderColor: colors.error },
  toggleText: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  toggleTextOn: { color: colors.bg },
  adHint: { color: colors.muted, fontSize: 12, marginTop: 10 },
  spacer: { height: 24 },
});
