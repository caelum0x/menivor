import { useCallback, useMemo, useState } from "react";
import {
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import {
  combineLocalDateTime,
  formatLocal,
  toDateField,
  toTimeField,
} from "./datetime";

/**
 * A dependency-free date/time picker: the user edits a local calendar date
 * ("YYYY-MM-DD") and wall-clock time ("HH:MM"), plus one-tap relative presets.
 * This is the "simple input" fallback for when
 * `@react-native-community/datetimepicker` is not installed (it is not a
 * dependency of this app). The component owns the two text fields and emits the
 * combined `Date` (or `null` when the input is incomplete/invalid) so the parent
 * can gate submission; it renders its own live local-time preview + inline
 * validation feedback.
 */
export interface DateTimeFieldProps {
  /** Seed value for the text fields (local time). */
  initialDate: Date;
  /** Called with the combined local `Date`, or `null` when invalid/incomplete. */
  onChange: (date: Date | null) => void;
  disabled?: boolean;
}

interface Preset {
  label: string;
  addMinutes: number;
}

/** One-tap relative offsets from "now", rounded to the minute. */
const PRESETS: readonly Preset[] = [
  { label: "+1 hour", addMinutes: 60 },
  { label: "+3 hours", addMinutes: 180 },
  { label: "Tomorrow", addMinutes: 24 * 60 },
  { label: "Next week", addMinutes: 7 * 24 * 60 },
];

export function DateTimeField({
  initialDate,
  onChange,
  disabled = false,
}: Readonly<DateTimeFieldProps>) {
  const [dateField, setDateField] = useState<string>(() =>
    toDateField(initialDate),
  );
  const [timeField, setTimeField] = useState<string>(() =>
    toTimeField(initialDate),
  );

  const combined = useMemo(
    () => combineLocalDateTime(dateField, timeField),
    [dateField, timeField],
  );

  const isPast = combined !== null && combined.getTime() <= Date.now();

  const emit = useCallback(
    (nextDate: string, nextTime: string) => {
      const next = combineLocalDateTime(nextDate, nextTime);
      onChange(next !== null && next.getTime() > Date.now() ? next : null);
    },
    [onChange],
  );

  const onChangeDate = useCallback(
    (text: string) => {
      setDateField(text);
      emit(text, timeField);
    },
    [emit, timeField],
  );

  const onChangeTime = useCallback(
    (text: string) => {
      setTimeField(text);
      emit(dateField, text);
    },
    [emit, dateField],
  );

  const applyPreset = useCallback(
    (preset: Preset) => {
      const next = new Date(Date.now() + preset.addMinutes * 60_000);
      next.setSeconds(0, 0);
      const nextDate = toDateField(next);
      const nextTime = toTimeField(next);
      setDateField(nextDate);
      setTimeField(nextTime);
      emit(nextDate, nextTime);
    },
    [emit],
  );

  return (
    <View style={styles.container}>
      <View style={styles.presetRow}>
        {PRESETS.map((preset) => (
          <Pressable
            key={preset.label}
            style={[styles.preset, disabled && styles.disabled]}
            onPress={() => applyPreset(preset)}
            disabled={disabled}
            accessibilityRole="button"
            accessibilityLabel={`Schedule ${preset.label}`}
          >
            <Text style={styles.presetText}>{preset.label}</Text>
          </Pressable>
        ))}
      </View>

      <View style={styles.inputsRow}>
        <View style={styles.inputCol}>
          <Text style={styles.inputLabel}>Date</Text>
          <TextInput
            style={styles.input}
            value={dateField}
            onChangeText={onChangeDate}
            editable={!disabled}
            placeholder="YYYY-MM-DD"
            placeholderTextColor="#5a5a6b"
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="numbers-and-punctuation"
            accessibilityLabel="Publish date, format year dash month dash day"
          />
        </View>
        <View style={styles.inputCol}>
          <Text style={styles.inputLabel}>Time</Text>
          <TextInput
            style={styles.input}
            value={timeField}
            onChangeText={onChangeTime}
            editable={!disabled}
            placeholder="HH:MM"
            placeholderTextColor="#5a5a6b"
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="numbers-and-punctuation"
            accessibilityLabel="Publish time, 24-hour format hours colon minutes"
          />
        </View>
      </View>

      {combined === null ? (
        <Text style={styles.hint}>
          Enter a date (YYYY-MM-DD) and 24-hour time (HH:MM) in your local time.
        </Text>
      ) : isPast ? (
        <Text style={styles.warn}>
          That time is in the past — pick a future time.
        </Text>
      ) : (
        <Text style={styles.preview}>Publishes {formatLocal(combined)}</Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { gap: 10 },
  presetRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  preset: {
    backgroundColor: "#0f0f10",
    borderColor: "#27272a",
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 7,
  },
  presetText: { color: "#ece9e1", fontSize: 13, fontWeight: "600" },
  disabled: { opacity: 0.5 },
  inputsRow: { flexDirection: "row", gap: 12 },
  inputCol: { flex: 1, gap: 6 },
  inputLabel: { color: "#8b8b9b", fontSize: 12, fontWeight: "600" },
  input: {
    backgroundColor: "#0f0f10",
    borderColor: "#27272a",
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: "#ece9e1",
    fontSize: 15,
  },
  hint: { color: "#6f6c65", fontSize: 13 },
  warn: { color: "#ff9a9a", fontSize: 13 },
  preview: { color: "#E6C76A", fontSize: 13, fontWeight: "600" },
});
