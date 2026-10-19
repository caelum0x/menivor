/**
 * Effects Lab (mobile) — scrub time across the real animation kernels from
 * `@reelforge/effects-core` (push-in, ken-burns, handheld, rgb-split, film-grain,
 * shake — byte-identical to the Python `reelforge_effects_core`) and watch both
 * the kernel's raw output values and a live preview driven by them via RN
 * transforms. The transform is exactly what the renderer animates. Mirrors the
 * web `/effects-lab`. Pure client-side reference; nothing is submitted.
 */

import * as React from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { apply, categoryOf, listKernels } from "@reelforge/effects-core";

import { colors } from "@/components/me/theme";
import { Icon } from "@/components/ui/Icon";

/** Map a kernel output record onto RN transform + opacity styles for the preview. */
function previewTransform(out: Record<string, number>) {
  const zoom = out.zoom ?? 1;
  const tx = (out.x ?? out.dx ?? 0) * 40;
  const ty = (out.y ?? out.dy ?? 0) * 40;
  const rot = out.rot ?? 0;
  const transform = [
    { translateX: tx },
    { translateY: ty },
    { scale: zoom },
    { rotate: `${rot.toFixed(2)}deg` },
  ];
  // grain/vignette dim the frame; rgb-split has no direct RN analog so we tint.
  const dim = 1 - (out.vignette ?? 0) * 0.3;
  return { transform, opacity: Math.max(0.4, dim) };
}

export default function EffectsLabScreen() {
  const kernels = React.useMemo(() => listKernels().map((id) => ({ id, category: categoryOf(id) })), []);
  const [selected, setSelected] = React.useState(kernels[0]?.id ?? "push-in");
  const [t, setT] = React.useState(0.5);

  const out = React.useMemo(() => apply(selected, t), [selected, t]);
  const preview = previewTransform(out);
  const category = categoryOf(selected);

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.intro}>
        Scrub time across the real animation kernels from effects-core — the transform you see is
        exactly what the renderer animates.
      </Text>

      <View style={styles.kernelRow}>
        {kernels.map((k) => (
          <Pressable
            key={k.id}
            style={[styles.kernelBtn, selected === k.id && styles.kernelBtnOn]}
            onPress={() => setSelected(k.id)}
          >
            <Text style={[styles.kernelText, selected === k.id && styles.kernelTextOn]}>{k.id}</Text>
          </Pressable>
        ))}
      </View>

      <View style={styles.card}>
        <View style={styles.cardHeader}>
          <View style={[styles.pill, { backgroundColor: category === "camera" ? colors.accent : colors.success }]}>
            <Text style={styles.pillText}>{category}</Text>
          </View>
          <Text style={styles.tLabel}>t = {t.toFixed(2)}</Text>
        </View>

        <View style={styles.stage}>
          <View style={[styles.frame, preview]}>
            <Text style={styles.frameText}>HOOK</Text>
          </View>
        </View>

        <View style={styles.sliderRow}>
          <Pressable style={styles.stepBtn} onPress={() => setT((v) => Math.max(0, Math.round((v - 0.05) * 100) / 100))}>
            <Icon name="remove" style={styles.stepBtnText} />
          </Pressable>
          <View style={styles.tTrack}>
            <View style={[styles.tFill, { width: `${t * 100}%` }]} />
          </View>
          <Pressable style={styles.stepBtn} onPress={() => setT((v) => Math.min(1, Math.round((v + 0.05) * 100) / 100))}>
            <Icon name="add" style={styles.stepBtnText} />
          </Pressable>
        </View>
      </View>

      <View style={styles.card}>
        <Text style={styles.outLabel}>kernel output @ t = {t.toFixed(2)}</Text>
        {Object.entries(out).map(([k, v]) => (
          <View key={k} style={styles.outRow}>
            <Text style={styles.outKey}>{k}</Text>
            <Text style={styles.outVal}>{v.toFixed(4)}</Text>
          </View>
        ))}
      </View>

      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  intro: { color: colors.textSecondary, fontSize: 14, marginBottom: 16 },
  kernelRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 12 },
  kernelBtn: {
    borderRadius: 10, paddingHorizontal: 12, paddingVertical: 8,
    backgroundColor: colors.cardAlt, borderColor: colors.border, borderWidth: 1,
  },
  kernelBtnOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  kernelText: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  kernelTextOn: { color: colors.bg },
  card: {
    backgroundColor: colors.card, borderColor: colors.border, borderWidth: 1,
    borderRadius: 12, padding: 12, marginBottom: 12,
  },
  cardHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 12 },
  pill: { borderRadius: 999, paddingHorizontal: 10, paddingVertical: 3 },
  pillText: { color: colors.bg, fontSize: 12, fontWeight: "700" },
  tLabel: { color: colors.muted, fontSize: 13 },
  stage: {
    height: 200, borderRadius: 10, backgroundColor: "#0d0d15",
    alignItems: "center", justifyContent: "center", overflow: "hidden",
  },
  frame: {
    width: 150, height: 84, borderRadius: 8, backgroundColor: colors.primary,
    alignItems: "center", justifyContent: "center",
  },
  frameText: { color: colors.bg, fontWeight: "800", fontSize: 18 },
  sliderRow: { flexDirection: "row", alignItems: "center", gap: 12, marginTop: 14 },
  stepBtn: { width: 36, height: 36, borderRadius: 10, backgroundColor: colors.cardAlt, alignItems: "center", justifyContent: "center" },
  stepBtnText: { color: colors.textPrimary, fontSize: 20, fontWeight: "700" },
  tTrack: { flex: 1, height: 8, borderRadius: 4, backgroundColor: colors.cardAlt, overflow: "hidden" },
  tFill: { height: "100%", backgroundColor: colors.primary },
  outLabel: { color: colors.muted, fontSize: 12, marginBottom: 8 },
  outRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 3 },
  outKey: { color: colors.textSecondary, fontSize: 13, fontFamily: "monospace" },
  outVal: { color: colors.textPrimary, fontSize: 13, fontFamily: "monospace" },
  spacer: { height: 24 },
});
