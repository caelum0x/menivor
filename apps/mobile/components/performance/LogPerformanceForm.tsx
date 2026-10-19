/**
 * Metrics-logging form for one selected reel. The creator enters the
 * self-reported outcome (platform + counts + watch-through %) and submits.
 * Presentational + local input state only — the parent owns the network call
 * (`logJobPerformance`) and passes `loading` for the submit affordance and an
 * optional `initial` row to pre-fill when the reel was already logged.
 *
 * All numbers are parsed defensively: counts are non-negative integers,
 * retention is clamped to [0,100], and an untouched field is simply omitted from
 * the request (the backend then leaves that column at its default).
 */

import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import {
  PERFORMANCE_PLATFORMS,
  type JobPerformance,
  type LogPerformanceRequest,
  type PerformancePlatform,
} from "@/lib/types";

import { colors } from "@/components/me/theme";
import { parseCount, parseRetention } from "./format";

interface LogPerformanceFormProps {
  loading: boolean;
  /** Existing row for the selected reel, used to pre-fill for an update. */
  initial?: JobPerformance | null;
  onSubmit: (body: LogPerformanceRequest) => void;
}

/** Blank string for an unset numeric field; a stored 0 shows as "0". */
function numToText(value: number | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "";
}

export function LogPerformanceForm({
  loading,
  initial,
  onSubmit,
}: LogPerformanceFormProps) {
  const [platform, setPlatform] = useState<PerformancePlatform>("tiktok");
  const [views, setViews] = useState("");
  const [likes, setLikes] = useState("");
  const [comments, setComments] = useState("");
  const [shares, setShares] = useState("");
  const [saves, setSaves] = useState("");
  const [retention, setRetention] = useState("");

  // Pre-fill from the stored row whenever the selected reel changes.
  useEffect(() => {
    const known = PERFORMANCE_PLATFORMS.find((p) => p === initial?.platform);
    setPlatform(known ?? "tiktok");
    setViews(numToText(initial?.views));
    setLikes(numToText(initial?.likes));
    setComments(numToText(initial?.comments));
    setShares(numToText(initial?.shares));
    setSaves(numToText(initial?.saves));
    setRetention(numToText(initial?.retention_pct));
  }, [initial]);

  const submit = () => {
    if (loading) return;
    onSubmit({
      platform,
      views: parseCount(views),
      likes: parseCount(likes),
      comments: parseCount(comments),
      shares: parseCount(shares),
      saves: parseCount(saves),
      retention_pct: parseRetention(retention),
    });
  };

  const isUpdate = !!initial;

  return (
    <View style={styles.form}>
      <Text style={styles.label}>Platform</Text>
      <View style={styles.chips}>
        {PERFORMANCE_PLATFORMS.map((p) => {
          const active = p === platform;
          return (
            <Pressable
              key={p}
              style={[styles.chip, active && styles.chipActive]}
              onPress={() => setPlatform(p)}
              disabled={loading}
            >
              <Text style={[styles.chipText, active && styles.chipTextActive]}>
                {p}
              </Text>
            </Pressable>
          );
        })}
      </View>

      <View style={styles.grid}>
        <NumberField label="Views" value={views} onChange={setViews} disabled={loading} />
        <NumberField label="Likes" value={likes} onChange={setLikes} disabled={loading} />
        <NumberField label="Comments" value={comments} onChange={setComments} disabled={loading} />
        <NumberField label="Shares" value={shares} onChange={setShares} disabled={loading} />
        <NumberField label="Saves" value={saves} onChange={setSaves} disabled={loading} />
        <NumberField
          label="Retention %"
          value={retention}
          onChange={setRetention}
          disabled={loading}
          hint="0–100"
        />
      </View>

      <Pressable
        style={[styles.primary, loading && styles.disabled]}
        onPress={submit}
        disabled={loading}
      >
        {loading ? (
          <ActivityIndicator color={colors.textPrimary} />
        ) : (
          <Text style={styles.primaryText}>
            {isUpdate ? "Update metrics" : "Log metrics"}
          </Text>
        )}
      </Pressable>
    </View>
  );
}

interface NumberFieldProps {
  label: string;
  value: string;
  onChange: (text: string) => void;
  disabled: boolean;
  hint?: string;
}

function NumberField({ label, value, onChange, disabled, hint }: NumberFieldProps) {
  return (
    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <TextInput
        style={styles.input}
        value={value}
        onChangeText={onChange}
        placeholder={hint ?? "0"}
        placeholderTextColor={colors.muted}
        keyboardType="number-pad"
        inputMode="numeric"
        maxLength={12}
        editable={!disabled}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  form: { gap: 12 },
  label: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { color: colors.textSecondary },
  chipTextActive: { color: colors.textPrimary, fontWeight: "700" },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  field: { flexBasis: "47%", flexGrow: 1, gap: 4 },
  fieldLabel: { color: colors.muted, fontSize: 12, fontWeight: "600" },
  input: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    color: colors.textPrimary,
    fontSize: 16,
    paddingHorizontal: 14,
    paddingVertical: 12,
  },
  primary: {
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: "center",
    marginTop: 4,
  },
  disabled: { opacity: 0.5 },
  primaryText: { color: colors.textPrimary, fontSize: 16, fontWeight: "700" },
});
