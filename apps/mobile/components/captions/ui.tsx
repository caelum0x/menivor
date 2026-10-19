/**
 * Shared presentational atoms for the Caption Studio screens. No data-fetching
 * here — just themed, reusable building blocks (cards, labelled inputs, chips,
 * steppers, result rows) so each tool screen stays focused on its own flow.
 */

import type { ReactNode } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { colors } from "@/components/me/theme";
import { Icon } from "@/components/ui/Icon";

interface SectionCardProps {
  title?: string;
  subtitle?: string;
  children: ReactNode;
}

export function SectionCard({ title, subtitle, children }: SectionCardProps) {
  return (
    <View style={styles.card}>
      {title ? <Text style={styles.cardTitle}>{title}</Text> : null}
      {subtitle ? <Text style={styles.cardSubtitle}>{subtitle}</Text> : null}
      {children}
    </View>
  );
}

interface LabeledInputProps {
  label: string;
  value: string;
  onChangeText: (v: string) => void;
  placeholder?: string;
  helper?: string;
  multiline?: boolean;
  keyboardType?: "default" | "numeric" | "decimal-pad";
  autoCapitalize?: "none" | "sentences";
}

export function LabeledInput({
  label,
  value,
  onChangeText,
  placeholder,
  helper,
  multiline,
  keyboardType = "default",
  autoCapitalize = "sentences",
}: LabeledInputProps) {
  return (
    <View style={styles.field}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        style={[styles.input, multiline ? styles.inputMultiline : null]}
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={colors.muted}
        multiline={multiline}
        keyboardType={keyboardType}
        autoCapitalize={autoCapitalize}
        autoCorrect={!multiline ? false : true}
      />
      {helper ? <Text style={styles.helper}>{helper}</Text> : null}
    </View>
  );
}

interface StepperProps {
  label: string;
  meta?: string;
  value: number;
  fraction: number;
  onStep: (delta: number) => void;
  step: number;
}

/** A −/+ stepper with a fill bar; `fraction` (0..1) drives the bar width. */
export function Stepper({ label, meta, value, fraction, onStep, step }: StepperProps) {
  const pct = `${Math.max(0, Math.min(100, fraction * 100))}%` as const;
  return (
    <View style={styles.stepperRow}>
      <View style={styles.stepperHeader}>
        <Text style={styles.stepperLabel}>{label}</Text>
        {meta ? <Text style={styles.stepperMeta}>{meta}</Text> : null}
      </View>
      <View style={styles.stepperControls}>
        <Pressable
          style={styles.stepBtn}
          onPress={() => onStep(-step)}
          accessibilityRole="button"
          accessibilityLabel={`Decrease ${label}`}
        >
          <Icon name="remove" style={styles.stepBtnText} />
        </Pressable>
        <View style={styles.valueTrack}>
          <View style={[styles.valueFill, { width: pct }]} />
        </View>
        <Pressable
          style={styles.stepBtn}
          onPress={() => onStep(step)}
          accessibilityRole="button"
          accessibilityLabel={`Increase ${label}`}
        >
          <Icon name="add" style={styles.stepBtnText} />
        </Pressable>
      </View>
      <Text style={styles.stepperValue}>{value.toFixed(2)}</Text>
    </View>
  );
}

interface ChipsProps<T extends string | number> {
  options: ReadonlyArray<{ id: T; label: string }>;
  selected: T;
  onSelect: (id: T) => void;
}

export function Chips<T extends string | number>({
  options,
  selected,
  onSelect,
}: ChipsProps<T>) {
  return (
    <View style={styles.chips}>
      {options.map((opt) => {
        const active = opt.id === selected;
        return (
          <Pressable
            key={String(opt.id)}
            style={[styles.chip, active ? styles.chipActive : null]}
            onPress={() => onSelect(opt.id)}
            accessibilityRole="button"
            accessibilityState={{ selected: active }}
          >
            <Text style={[styles.chipText, active ? styles.chipTextActive : null]}>
              {opt.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

interface TagListProps {
  tags: string[];
  tone?: "accent" | "muted";
}

export function TagList({ tags, tone = "muted" }: TagListProps) {
  if (tags.length === 0) return null;
  return (
    <View style={styles.tags}>
      {tags.map((t, i) => (
        <View
          key={`${t}-${i}`}
          style={[styles.tag, tone === "accent" ? styles.tagAccent : null]}
        >
          <Text style={[styles.tagText, tone === "accent" ? styles.tagTextAccent : null]}>
            {t}
          </Text>
        </View>
      ))}
    </View>
  );
}

interface KeyValueRowProps {
  label: string;
  value: string;
  strong?: boolean;
}

export function KeyValueRow({ label, value, strong }: KeyValueRowProps) {
  return (
    <View style={styles.kvRow}>
      <Text style={styles.kvLabel}>{label}</Text>
      <Text style={[styles.kvValue, strong ? styles.kvValueStrong : null]}>{value}</Text>
    </View>
  );
}

interface PrimaryButtonProps {
  label: string;
  onPress: () => void;
  loading?: boolean;
  disabled?: boolean;
}

export function PrimaryButton({ label, onPress, loading, disabled }: PrimaryButtonProps) {
  const isDisabled = disabled || loading;
  return (
    <Pressable
      style={[styles.primaryBtn, isDisabled ? styles.primaryBtnDisabled : null]}
      onPress={onPress}
      disabled={isDisabled}
      accessibilityRole="button"
      accessibilityState={{ disabled: !!isDisabled }}
    >
      {loading ? (
        <ActivityIndicator color={colors.bg} />
      ) : (
        <Text style={styles.primaryBtnText}>{label}</Text>
      )}
    </Pressable>
  );
}

interface InlineErrorProps {
  message: string;
}

export function InlineError({ message }: InlineErrorProps) {
  if (!message) return null;
  return (
    <View style={styles.errorBox}>
      <Text style={styles.errorText}>{message}</Text>
    </View>
  );
}

/** A horizontal 0..1 meter with an optional gate marker. */
export function Meter({
  fraction,
  color,
  gate,
}: {
  fraction: number;
  color: string;
  gate?: number;
}) {
  const width = `${Math.max(0, Math.min(100, fraction * 100))}%` as const;
  return (
    <View style={styles.meter}>
      {typeof gate === "number" ? (
        <View style={[styles.meterGate, { left: `${gate * 100}%` }]} />
      ) : null}
      <View style={[styles.meterFill, { width, backgroundColor: color }]} />
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    marginBottom: 14,
    gap: 10,
  },
  cardTitle: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  cardSubtitle: { color: colors.muted, fontSize: 12, lineHeight: 18 },
  field: { gap: 6 },
  label: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  input: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    color: colors.textPrimary,
    fontSize: 15,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  inputMultiline: { minHeight: 96, textAlignVertical: "top" },
  helper: { color: colors.muted, fontSize: 12 },
  stepperRow: { gap: 8, marginBottom: 4 },
  stepperHeader: { flexDirection: "row", justifyContent: "space-between" },
  stepperLabel: { color: colors.textPrimary, fontSize: 14, fontWeight: "600" },
  stepperMeta: { color: colors.muted, fontSize: 12 },
  stepperControls: { flexDirection: "row", alignItems: "center", gap: 12 },
  stepperValue: { color: colors.muted, fontSize: 12, textAlign: "right" },
  stepBtn: {
    width: 36,
    height: 36,
    borderRadius: 10,
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  stepBtnText: { color: colors.textPrimary, fontSize: 20, fontWeight: "700" },
  valueTrack: {
    flex: 1,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.cardAlt,
    overflow: "hidden",
  },
  valueFill: { height: "100%", backgroundColor: colors.primary },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 7,
    backgroundColor: colors.cardAlt,
  },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  chipTextActive: { color: colors.bg },
  tags: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  tag: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 5,
    backgroundColor: colors.cardAlt,
  },
  tagAccent: { backgroundColor: colors.primary, borderColor: colors.primary },
  tagText: { color: colors.textSecondary, fontSize: 13 },
  tagTextAccent: { color: colors.bg, fontWeight: "700" },
  kvRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingVertical: 6,
    borderBottomColor: colors.border,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  kvLabel: { color: colors.textSecondary, fontSize: 13 },
  kvValue: { color: colors.textPrimary, fontSize: 13, fontWeight: "600" },
  kvValueStrong: { fontSize: 15, fontWeight: "800" },
  primaryBtn: {
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
    justifyContent: "center",
    minHeight: 50,
  },
  primaryBtnDisabled: { opacity: 0.5 },
  primaryBtnText: { color: colors.bg, fontSize: 15, fontWeight: "800" },
  errorBox: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.error,
    borderWidth: 1,
    borderRadius: 10,
    padding: 12,
  },
  errorText: { color: colors.error, fontSize: 13 },
  meter: {
    width: "100%",
    height: 10,
    borderRadius: 5,
    backgroundColor: colors.cardAlt,
    marginTop: 4,
    position: "relative",
    overflow: "hidden",
  },
  meterGate: { position: "absolute", top: 0, bottom: 0, width: 2, backgroundColor: "#fbbf24" },
  meterFill: { height: "100%", borderRadius: 5 },
});

export const captionStyles = styles;
