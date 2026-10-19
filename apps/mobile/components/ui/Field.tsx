/**
 * Field primitive — covers text, number, select (inline picker), toggle, and date.
 * Each variant has a consistent label + optional error + helper layout.
 * No emoji. Explicit typed props.
 */

import type { ReactNode } from "react";
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
  type KeyboardTypeOptions,
  type StyleProp,
  type ViewStyle,
} from "react-native";

import { colors } from "@/components/me/theme";
import { radius, spacing, weight } from "@/src/shared/theme";

// ---------------------------------------------------------------------------
// Shared label + error wrapper
// ---------------------------------------------------------------------------

interface FieldWrapperProps {
  label?: string;
  error?: string;
  helper?: string;
  required?: boolean;
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
}

export function FieldWrapper({
  label,
  error,
  helper,
  required,
  children,
  style,
}: FieldWrapperProps): React.JSX.Element {
  return (
    <View style={[styles.wrapper, style]}>
      {label ? (
        <Text style={styles.label}>
          {label}
          {required ? <Text style={styles.required}> *</Text> : null}
        </Text>
      ) : null}
      {children}
      {error ? <Text style={styles.error}>{error}</Text> : null}
      {!error && helper ? (
        <Text style={styles.helper}>{helper}</Text>
      ) : null}
    </View>
  );
}

// ---------------------------------------------------------------------------
// TextField
// ---------------------------------------------------------------------------

export interface TextFieldProps {
  label?: string;
  value: string;
  onChangeText: (text: string) => void;
  placeholder?: string;
  error?: string;
  helper?: string;
  required?: boolean;
  multiline?: boolean;
  numberOfLines?: number;
  editable?: boolean;
  keyboardType?: KeyboardTypeOptions;
  autoCapitalize?: "none" | "sentences" | "words" | "characters";
  secureTextEntry?: boolean;
  style?: StyleProp<ViewStyle>;
  maxLength?: number;
}

export function TextField({
  label,
  value,
  onChangeText,
  placeholder,
  error,
  helper,
  required,
  multiline = false,
  numberOfLines = 3,
  editable = true,
  keyboardType = "default",
  autoCapitalize = "sentences",
  secureTextEntry = false,
  style,
  maxLength,
}: TextFieldProps): React.JSX.Element {
  return (
    <FieldWrapper label={label} error={error} helper={helper} required={required} style={style}>
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={colors.muted}
        editable={editable}
        multiline={multiline}
        numberOfLines={multiline ? numberOfLines : 1}
        keyboardType={keyboardType}
        autoCapitalize={autoCapitalize}
        secureTextEntry={secureTextEntry}
        maxLength={maxLength}
        style={[
          styles.input,
          !!error && styles.inputError,
          !editable && styles.inputDisabled,
          multiline && styles.inputMultiline,
        ]}
      />
    </FieldWrapper>
  );
}

// ---------------------------------------------------------------------------
// NumberField — thin wrapper, forces numeric keyboard
// ---------------------------------------------------------------------------

export interface NumberFieldProps extends Omit<TextFieldProps, "keyboardType" | "multiline" | "autoCapitalize"> {
  value: string;
}

export function NumberField({ ...props }: NumberFieldProps): React.JSX.Element {
  return (
    <TextField
      {...props}
      keyboardType="numeric"
      autoCapitalize="none"
      multiline={false}
    />
  );
}

// ---------------------------------------------------------------------------
// SelectField — pressable trigger + inline option list
// ---------------------------------------------------------------------------

export interface SelectOption<T extends string = string> {
  value: T;
  label: string;
}

export interface SelectFieldProps<T extends string = string> {
  label?: string;
  value: T | null;
  onChange: (value: T) => void;
  options: readonly SelectOption<T>[];
  placeholder?: string;
  error?: string;
  helper?: string;
  required?: boolean;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
}

export function SelectField<T extends string = string>({
  label,
  value,
  onChange,
  options,
  placeholder = "Select…",
  error,
  helper,
  required,
  disabled = false,
  style,
}: SelectFieldProps<T>): React.JSX.Element {
  const selected = options.find((o) => o.value === value);

  return (
    <FieldWrapper label={label} error={error} helper={helper} required={required} style={style}>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.selectRow}
      >
        {options.map((opt) => {
          const active = opt.value === value;
          return (
            <Pressable
              key={opt.value}
              onPress={() => !disabled && onChange(opt.value)}
              accessibilityRole="radio"
              accessibilityState={{ checked: active, disabled }}
              style={[
                styles.selectChip,
                active && styles.selectChipActive,
                disabled && styles.selectChipDisabled,
              ]}
            >
              <Text
                style={[styles.selectChipLabel, active && styles.selectChipLabelActive]}
              >
                {opt.label}
              </Text>
            </Pressable>
          );
        })}
      </ScrollView>
      {!options.length ? (
        <Text style={styles.helper}>{placeholder}</Text>
      ) : null}
    </FieldWrapper>
  );
}

// ---------------------------------------------------------------------------
// ToggleField
// ---------------------------------------------------------------------------

export interface ToggleFieldProps {
  label: string;
  value: boolean;
  onValueChange: (value: boolean) => void;
  helper?: string;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
}

export function ToggleField({
  label,
  value,
  onValueChange,
  helper,
  disabled = false,
  style,
}: ToggleFieldProps): React.JSX.Element {
  return (
    <View style={[styles.toggleRow, style]}>
      <View style={styles.toggleBody}>
        <Text style={styles.toggleLabel}>{label}</Text>
        {helper ? <Text style={styles.helper}>{helper}</Text> : null}
      </View>
      <Switch
        value={value}
        onValueChange={onValueChange}
        disabled={disabled}
        trackColor={{ false: colors.border, true: colors.accent }}
        thumbColor={colors.textPrimary}
      />
    </View>
  );
}

// ---------------------------------------------------------------------------
// DateField — text input with date-shaped placeholder
// ---------------------------------------------------------------------------

export interface DateFieldProps {
  label?: string;
  /** ISO-8601 datetime string value. */
  value: string;
  onChangeText: (text: string) => void;
  placeholder?: string;
  error?: string;
  helper?: string;
  required?: boolean;
  editable?: boolean;
  style?: StyleProp<ViewStyle>;
}

export function DateField({
  placeholder = "YYYY-MM-DDTHH:MM",
  ...props
}: DateFieldProps): React.JSX.Element {
  return (
    <TextField
      {...props}
      placeholder={placeholder}
      keyboardType="default"
      autoCapitalize="none"
      multiline={false}
    />
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles = StyleSheet.create({
  wrapper: { gap: spacing.xs + 2 },

  label: {
    color: colors.textSecondary,
    fontSize: 13,
    fontWeight: weight.semibold,
    letterSpacing: 0.4,
  },
  required: { color: colors.error },
  error: { color: colors.error, fontSize: 12 },
  helper: { color: colors.muted, fontSize: 12 },

  input: {
    backgroundColor: colors.cardAlt,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm + 2,
    color: colors.textPrimary,
    fontSize: 15,
  },
  inputError: { borderColor: colors.error },
  inputDisabled: { opacity: 0.5 },
  inputMultiline: { minHeight: 80, textAlignVertical: "top", paddingTop: spacing.sm },

  selectRow: { flexDirection: "row", gap: spacing.sm, paddingVertical: 2 },
  selectChip: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs + 2,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
  },
  selectChipActive: { backgroundColor: colors.accent, borderColor: colors.accent },
  selectChipDisabled: { opacity: 0.5 },
  selectChipLabel: { color: colors.textSecondary, fontSize: 13, fontWeight: weight.bold },
  selectChipLabelActive: { color: colors.bg },

  toggleRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    justifyContent: "space-between",
  },
  toggleBody: { flex: 1, gap: 2 },
  toggleLabel: { color: colors.textPrimary, fontSize: 15, fontWeight: weight.semibold },
});
