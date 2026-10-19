/**
 * Model Governance (mobile) — the license-class + lifecycle gates from
 * `@reelforge/provider-adapter-kit` (byte-identical to the Python `license.py`/
 * `deprecation.py`), applied to every catalogued model: can it back a *paid*
 * render (commercial-safe only), and is it active / deprecating / sunset as of a
 * chosen date? Step the date forward to see which models sunset when. Mirrors the
 * web `/model-governance`. Read-only reference; nothing is submitted.
 */

import * as React from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import {
  DEPRECATION_REGISTRY,
  LICENSE_REGISTRY,
  canUseForPaid,
  licenseClass,
  migrate,
  type LicenseClass,
  type Lifecycle,
} from "@reelforge/provider-adapter-kit";

import { colors } from "@/components/me/theme";

const LICENSE_COLOR: Record<LicenseClass, string> = {
  "commercial-safe": colors.success,
  territorial: "#fbbf24",
  "non-commercial": colors.error,
};

const LIFECYCLE_COLOR: Record<Lifecycle, string> = {
  active: colors.success,
  deprecating: "#fbbf24",
  sunset: colors.error,
};

const MODELS = Array.from(
  new Set([...Object.keys(LICENSE_REGISTRY), ...Object.keys(DEPRECATION_REGISTRY)]),
).sort();

/** Add `days` to an ISO date (UTC), returning YYYY-MM-DD. */
function shiftISO(iso: string, days: number): string {
  const base = Date.parse(`${iso}T00:00:00Z`);
  return new Date(base + days * 86_400_000).toISOString().slice(0, 10);
}

export default function ModelGovernanceScreen() {
  const [today, setToday] = React.useState(() => new Date().toISOString().slice(0, 10));

  const rows = React.useMemo(
    () =>
      MODELS.map((model) => ({
        model,
        klass: licenseClass(model),
        paid: canUseForPaid(model),
        hint: migrate(model, today),
      })),
    [today],
  );

  const paidSafe = rows.filter((r) => r.paid).length;
  const migrating = rows.filter((r) => r.hint.should_migrate).length;

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.intro}>
        License-class and lifecycle gates from provider-adapter-kit — the same rules the gateway
        enforces before a model backs a paid render.
      </Text>

      <View style={styles.card}>
        <View style={styles.dateRow}>
          <Pressable style={styles.stepBtn} onPress={() => setToday((d) => shiftISO(d, -90))}>
            <Text style={styles.stepBtnText}>−90d</Text>
          </Pressable>
          <Text style={styles.dateText}>as of {today}</Text>
          <Pressable style={styles.stepBtn} onPress={() => setToday((d) => shiftISO(d, 90))}>
            <Text style={styles.stepBtnText}>+90d</Text>
          </Pressable>
        </View>
        <View style={styles.summaryRow}>
          <View style={[styles.pill, { backgroundColor: colors.success }]}>
            <Text style={styles.pillText}>{paidSafe}/{rows.length} paid-safe</Text>
          </View>
          <View style={[styles.pill, { backgroundColor: migrating ? "#fbbf24" : colors.success }]}>
            <Text style={styles.pillText}>{migrating} need migration</Text>
          </View>
        </View>
      </View>

      {rows.map((r) => (
        <View key={r.model} style={styles.card}>
          <Text style={styles.model}>{r.model}</Text>
          <View style={styles.badgeRow}>
            <View style={[styles.badge, { borderColor: LICENSE_COLOR[r.klass] }]}>
              <Text style={[styles.badgeText, { color: LICENSE_COLOR[r.klass] }]}>{r.klass}</Text>
            </View>
            <View style={[styles.badge, { borderColor: LIFECYCLE_COLOR[r.hint.status] }]}>
              <Text style={[styles.badgeText, { color: LIFECYCLE_COLOR[r.hint.status] }]}>{r.hint.status}</Text>
            </View>
            <Text style={[styles.paid, { color: r.paid ? colors.success : colors.muted }]}>
              {r.paid ? "Paid" : "Unpaid"}
            </Text>
          </View>
          {r.hint.should_migrate && r.hint.replacement ? (
            <Text style={styles.migrate}>Migrate to {r.hint.replacement}</Text>
          ) : null}
        </View>
      ))}

      <Text style={styles.footnote}>
        Only commercial-safe models may back a paid render; territorial and non-commercial are gated.
        Unknown models default to territorial (gate-before-use).
      </Text>
      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  intro: { color: colors.textSecondary, fontSize: 14, marginBottom: 16 },
  card: {
    backgroundColor: colors.card, borderColor: colors.border, borderWidth: 1,
    borderRadius: 12, padding: 12, marginBottom: 10,
  },
  dateRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  dateText: { color: colors.textPrimary, fontSize: 14, fontWeight: "600" },
  stepBtn: { borderRadius: 8, paddingHorizontal: 12, paddingVertical: 8, backgroundColor: colors.cardAlt },
  stepBtnText: { color: colors.textPrimary, fontSize: 13, fontWeight: "700" },
  summaryRow: { flexDirection: "row", gap: 8, marginTop: 12 },
  pill: { borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 },
  pillText: { color: colors.bg, fontSize: 12, fontWeight: "700" },
  model: { color: colors.textPrimary, fontSize: 13, fontFamily: "monospace", marginBottom: 8 },
  badgeRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  badge: { borderWidth: 1, borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 },
  badgeText: { fontSize: 11, fontWeight: "700" },
  paid: { fontSize: 12, fontWeight: "600", marginLeft: "auto" },
  migrate: { color: colors.muted, fontSize: 12, marginTop: 8 },
  footnote: { color: colors.muted, fontSize: 12, marginTop: 8 },
  spacer: { height: 24 },
});
