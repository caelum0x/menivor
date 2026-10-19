/**
 * Spend & usage screen (Expo). The caller's monthly budget + spend this month,
 * an in-app editor for the budget cap and BYOK consent (PUT /spend/policy), and
 * cost attribution by provider/stage. Token comes from the session (sent as
 * `x-api-key`).
 */

import * as React from "react";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
} from "react-native";

import { parseUsdMicros } from "@/lib/wallet";

import { colors } from "@/components/me/theme";
import { useSession } from "@/src/shared/auth";
import { ApiError } from "@/src/shared/api";
import {
  formatUsdMicros,
  getSpendPolicy,
  getUsageSummary,
  updateSpendPolicy,
  type SpendPolicy,
  type UsageGroup,
  type UsageSummary,
} from "@/lib/marketplace";

export default function SpendScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const [policy, setPolicy] = React.useState<SpendPolicy | null>(null);
  const [usage, setUsage] = React.useState<UsageSummary | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");

  const load = React.useCallback(async () => {
    setError("");
    try {
      const [p, u] = await Promise.all([
        getSpendPolicy({ token }),
        getUsageSummary({ token }, 30),
      ]);
      setPolicy(p);
      setUsage(u);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Failed to load spend.",
      );
    } finally {
      setLoading(false);
    }
  }, [token]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const budget = policy?.monthly_budget_micros ?? 0;
  const spent = policy?.period_spend_micros ?? 0;
  const pct = budget > 0 ? Math.min(100, (spent / budget) * 100) : 0;

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      refreshControl={
        <RefreshControl
          refreshing={loading && policy !== null}
          onRefresh={() => {
            setLoading(true);
            void load();
          }}
          tintColor={colors.primary}
        />
      }
    >
      {loading && !policy ? (
        <ActivityIndicator color={colors.primary} style={styles.spinner} />
      ) : error ? (
        <Text style={styles.error}>{error}</Text>
      ) : (
        <>
          <View style={styles.card}>
            <Text style={styles.cardLabel}>Spent this month</Text>
            <Text style={styles.cardValue}>
              {formatUsdMicros(spent)}
              {budget > 0 ? ` / ${formatUsdMicros(budget)}` : " (no cap)"}
            </Text>
            {budget > 0 && (
              <View style={styles.track}>
                <View
                  style={[
                    styles.fill,
                    { width: `${pct}%`, backgroundColor: pct >= 100 ? "#f87171" : colors.primary },
                  ]}
                />
              </View>
            )}
          </View>

          <Text style={styles.sectionTitle}>
            By provider · last {usage?.days ?? 30} days · {usage?.total_cost_usd ?? "$0.00"}
          </Text>
          <Breakdown rows={usage?.by_provider ?? []} />
          <Text style={styles.sectionTitle}>By stage</Text>
          <Breakdown rows={usage?.by_stage ?? []} />

          {policy ? (
            <PolicyEditor
              policy={policy}
              token={token}
              onSaved={(next) => setPolicy(next)}
            />
          ) : null}
        </>
      )}
    </ScrollView>
  );
}

/** Microdollars to an editable "12.50"-style USD string ("" for no cap). */
function microsToInput(micros: number): string {
  if (micros <= 0) return "";
  const usd = micros / 1_000_000;
  return Number.isInteger(usd) ? String(usd) : usd.toFixed(2);
}

/** Parse the budget field: blank or 0 means no cap; null means invalid. */
function inputToMicros(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "" || /^0+(\.0*)?$/.test(trimmed)) return 0;
  return parseUsdMicros(trimmed);
}

function PolicyEditor({
  policy,
  token,
  onSaved,
}: {
  policy: SpendPolicy;
  token: string | undefined;
  onSaved: (next: SpendPolicy) => void;
}) {
  const [budget, setBudget] = React.useState(() => microsToInput(policy.monthly_budget_micros));
  const [byok, setByok] = React.useState(policy.byok_allowed);
  const [saving, setSaving] = React.useState(false);
  const [message, setMessage] = React.useState<{ ok: boolean; text: string } | null>(null);

  React.useEffect(() => {
    setBudget(microsToInput(policy.monthly_budget_micros));
    setByok(policy.byok_allowed);
  }, [policy.monthly_budget_micros, policy.byok_allowed]);

  const micros = inputToMicros(budget);
  const dirty =
    micros !== null &&
    (micros !== policy.monthly_budget_micros || byok !== policy.byok_allowed);

  const onSave = async () => {
    if (micros === null) {
      setMessage({ ok: false, text: "Enter a dollar amount like 25 or 25.50, or leave it blank for no cap." });
      return;
    }
    setSaving(true);
    setMessage(null);
    try {
      const next = await updateSpendPolicy(
        { monthly_budget_micros: micros, byok_allowed: byok },
        { token },
      );
      onSaved({ ...policy, ...next });
      setMessage({ ok: true, text: "Spend settings saved." });
    } catch (err) {
      setMessage({
        ok: false,
        text: err instanceof Error ? err.message : "Couldn't save spend settings.",
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <View style={[styles.card, styles.editor]}>
      <Text style={styles.editorTitle}>Spend settings</Text>
      <Text style={styles.cardLabel}>Monthly budget (USD)</Text>
      <View style={styles.inputRow}>
        <Text style={styles.dollar}>$</Text>
        <TextInput
          style={styles.input}
          value={budget}
          onChangeText={setBudget}
          placeholder="No cap"
          placeholderTextColor={colors.muted}
          keyboardType="decimal-pad"
          inputMode="decimal"
          editable={!saving}
          accessibilityLabel="Monthly budget in US dollars"
        />
      </View>
      <Text style={styles.hint}>
        Generation stops once this month's spend reaches the cap. Leave blank for no cap.
      </Text>
      <View style={styles.switchRow}>
        <View style={styles.switchBody}>
          <Text style={styles.switchTitle}>Allow my own provider keys (BYOK)</Text>
          <Text style={styles.hint}>
            When on, renders may run on the provider keys you saved under Provider Keys and bill
            your provider account instead of your wallet.
          </Text>
        </View>
        <Switch
          value={byok}
          onValueChange={setByok}
          disabled={saving}
          accessibilityLabel="Allow bring-your-own-key renders"
          trackColor={{ true: colors.primary, false: colors.cardAlt }}
        />
      </View>
      <Pressable
        style={[styles.save, (!dirty || saving) && styles.saveDisabled]}
        onPress={() => void onSave()}
        disabled={!dirty || saving}
        accessibilityRole="button"
      >
        {saving ? (
          <ActivityIndicator color={colors.bg} />
        ) : (
          <Text style={styles.saveText}>Save</Text>
        )}
      </Pressable>
      {message ? (
        <Text style={message.ok ? styles.ok : styles.error}>{message.text}</Text>
      ) : null}
    </View>
  );
}

function Breakdown({ rows }: { rows: UsageGroup[] }) {
  if (rows.length === 0) {
    return <Text style={styles.empty}>No usage yet.</Text>;
  }
  return (
    <View style={styles.list}>
      {rows.map((row) => (
        <View key={row.key} style={styles.row}>
          <Text style={styles.rowKey} numberOfLines={1}>
            {row.key || "—"}
          </Text>
          <Text style={styles.rowVal}>
            {row.cost_usd} · {row.runs}
          </Text>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20 },
  spinner: { marginTop: 40 },
  error: { color: "#f87171", fontSize: 14, marginTop: 20 },
  card: {
    backgroundColor: colors.card,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 16,
  },
  cardLabel: { color: colors.textSecondary, fontSize: 13 },
  cardValue: { color: colors.textPrimary, fontSize: 22, fontWeight: "700", marginTop: 6 },
  track: { marginTop: 12, height: 8, borderRadius: 999, backgroundColor: colors.cardAlt, overflow: "hidden" },
  fill: { height: "100%", borderRadius: 999 },
  sectionTitle: { color: colors.textPrimary, fontSize: 15, fontWeight: "600", marginTop: 24, marginBottom: 8 },
  empty: { color: colors.textSecondary, fontSize: 13, paddingVertical: 8 },
  list: { borderWidth: 1, borderColor: colors.border, borderRadius: 12, overflow: "hidden" },
  row: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    gap: 12,
  },
  rowKey: { color: colors.textPrimary, fontSize: 14, flex: 1 },
  rowVal: { color: colors.textSecondary, fontSize: 13, fontVariant: ["tabular-nums"] },
  editor: { marginTop: 24, gap: 8 },
  editorTitle: { color: colors.textPrimary, fontSize: 16, fontWeight: "700", marginBottom: 4 },
  inputRow: {
    flexDirection: "row",
    alignItems: "center",
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 12,
  },
  dollar: { color: colors.textSecondary, fontSize: 16, fontWeight: "600" },
  input: { flex: 1, color: colors.textPrimary, fontSize: 16, paddingVertical: 10, paddingLeft: 4 },
  hint: { color: colors.textSecondary, fontSize: 12, lineHeight: 17 },
  switchRow: { flexDirection: "row", alignItems: "center", gap: 12, marginTop: 8 },
  switchBody: { flex: 1, gap: 4 },
  switchTitle: { color: colors.textPrimary, fontSize: 14, fontWeight: "600" },
  save: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
    marginTop: 8,
  },
  saveDisabled: { opacity: 0.5 },
  saveText: { color: colors.bg, fontSize: 15, fontWeight: "700" },
  ok: { color: colors.success, fontSize: 13 },
});
