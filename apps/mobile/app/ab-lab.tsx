/**
 * A/B Winner Lab (mobile) — an interactive tool over the real
 * `@reelforge/growth-analytics.selectWinner`, the retention-weighted variant
 * picker (byte-identical to `ab.py`) the pipeline promotes the best cut with:
 * `score = 0.6·completion + 0.4·(avg_watch ÷ best)`. Adjust each variant's
 * completion + avg-watch and watch the scores + winner update live. Mirrors the
 * web `/ab-lab`. Pure client-side reference; nothing is submitted.
 */

import * as React from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { selectWinner, type Variant } from "@reelforge/growth-analytics";

import { colors } from "@/components/me/theme";
import { Icon } from "@/components/ui/Icon";

interface Row {
  id: string;
  completion: number;
  avg_watch: number;
}

export default function AbLabScreen() {
  const nextId = React.useRef(4);
  const [rows, setRows] = React.useState<Row[]>([
    { id: "A", completion: 0.55, avg_watch: 12 },
    { id: "B", completion: 0.42, avg_watch: 18 },
    { id: "C", completion: 0.6, avg_watch: 9 },
  ]);

  const result = React.useMemo(
    () =>
      selectWinner(
        rows.map<Variant>((r) => ({ id: r.id, completion: r.completion, avg_watch: r.avg_watch })),
      ),
    [rows],
  );

  const patch = (id: string, key: "completion" | "avg_watch", delta: number) =>
    setRows((prev) =>
      prev.map((r) => {
        if (r.id !== id) return r;
        if (key === "completion") return { ...r, completion: Math.max(0, Math.min(1, Math.round((r.completion + delta) * 100) / 100)) };
        return { ...r, avg_watch: Math.max(0, Math.min(60, Math.round(r.avg_watch + delta))) };
      }),
    );

  const addRow = () =>
    setRows((prev) => [
      ...prev,
      { id: String.fromCharCode(64 + ++nextId.current), completion: 0.5, avg_watch: 10 },
    ]);

  const removeRow = (id: string) =>
    setRows((prev) => (prev.length <= 2 ? prev : prev.filter((r) => r.id !== id)));

  const ranked = [...rows].sort((a, b) => (result.scores[b.id] ?? 0) - (result.scores[a.id] ?? 0));

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.intro}>
        The retention-weighted variant picker the pipeline promotes with — identical to the renderer
        via growth-analytics. Score = 0.6·completion + 0.4·(avg_watch ÷ best).
      </Text>

      <View style={styles.headerRow}>
        <Text style={styles.winnerLabel}>
          Winner:{" "}
          {result.winner ? <Text style={styles.winnerId}>Variant {result.winner}</Text> : "—"}
        </Text>
        <Pressable style={styles.addBtn} onPress={addRow}>
          <Text style={styles.addBtnText}>+ Add</Text>
        </Pressable>
      </View>

      {ranked.map((r) => {
        const score = result.scores[r.id] ?? 0;
        const isWinner = r.id === result.winner;
        return (
          <View key={r.id} style={[styles.card, isWinner && styles.cardWinner]}>
            <View style={styles.cardHeader}>
              <View style={styles.cardTitleRow}>
                <Text style={styles.cardTitle}>Variant {r.id}</Text>
                {isWinner ? (
                  <View style={styles.pill}>
                    <Text style={styles.pillText}>winner</Text>
                  </View>
                ) : null}
              </View>
              <View style={styles.cardTitleRow}>
                <Text style={[styles.score, isWinner && { color: colors.success }]}>{Math.round(score * 100)}%</Text>
                <Pressable
                  style={[styles.iconBtn, rows.length <= 2 && styles.disabled]}
                  disabled={rows.length <= 2}
                  onPress={() => removeRow(r.id)}
                >
                  <Icon name="close" style={styles.iconBtnText} />
                </Pressable>
              </View>
            </View>

            <Stepper label="Completion" display={`${Math.round(r.completion * 100)}%`}
              onDec={() => patch(r.id, "completion", -0.05)} onInc={() => patch(r.id, "completion", 0.05)} />
            <Stepper label="Avg watch" display={`${r.avg_watch}s`}
              onDec={() => patch(r.id, "avg_watch", -1)} onInc={() => patch(r.id, "avg_watch", 1)} />

            <View style={styles.track}>
              <View style={[styles.fill, { width: `${Math.min(100, score * 100)}%`, backgroundColor: isWinner ? colors.success : colors.primary }]} />
            </View>
          </View>
        );
      })}

      <View style={styles.spacer} />
    </ScrollView>
  );
}

function Stepper({ label, display, onDec, onInc }: { label: string; display: string; onDec: () => void; onInc: () => void }) {
  return (
    <View style={styles.stepper}>
      <Text style={styles.stepLabel}>{label}</Text>
      <View style={styles.stepControls}>
        <Pressable style={styles.stepBtn} onPress={onDec}>
          <Icon name="remove" style={styles.stepBtnText} />
        </Pressable>
        <Text style={styles.stepValue}>{display}</Text>
        <Pressable style={styles.stepBtn} onPress={onInc}>
          <Icon name="add" style={styles.stepBtnText} />
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  intro: { color: colors.textSecondary, fontSize: 14, marginBottom: 16 },
  headerRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 12 },
  winnerLabel: { color: colors.textPrimary, fontSize: 14 },
  winnerId: { color: colors.success, fontWeight: "700" },
  addBtn: { backgroundColor: colors.cardAlt, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 8 },
  addBtnText: { color: colors.textPrimary, fontSize: 13, fontWeight: "600" },
  card: {
    backgroundColor: colors.card, borderColor: colors.border, borderWidth: 1,
    borderRadius: 12, padding: 12, marginBottom: 10,
  },
  cardWinner: { borderColor: colors.success },
  cardHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 6 },
  cardTitleRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  cardTitle: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  pill: { backgroundColor: colors.success, borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 },
  pillText: { color: colors.bg, fontSize: 11, fontWeight: "700" },
  score: { color: colors.textPrimary, fontSize: 20, fontWeight: "700" },
  iconBtn: { width: 32, height: 32, borderRadius: 8, backgroundColor: colors.cardAlt, alignItems: "center", justifyContent: "center" },
  iconBtnText: { color: colors.textPrimary, fontSize: 14, fontWeight: "700" },
  disabled: { opacity: 0.3 },
  stepper: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: 8 },
  stepLabel: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  stepControls: { flexDirection: "row", alignItems: "center", gap: 12 },
  stepBtn: { width: 32, height: 32, borderRadius: 8, backgroundColor: colors.cardAlt, alignItems: "center", justifyContent: "center" },
  stepBtnText: { color: colors.textPrimary, fontSize: 18, fontWeight: "700" },
  stepValue: { color: colors.textPrimary, fontSize: 14, minWidth: 48, textAlign: "center" },
  track: { height: 6, borderRadius: 3, backgroundColor: colors.cardAlt, marginTop: 12, overflow: "hidden" },
  fill: { height: "100%", borderRadius: 3 },
  spacer: { height: 24 },
});
