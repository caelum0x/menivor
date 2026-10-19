import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

/**
 * Jobs-library selectable chips for a single re-run override. A leading
 * "Keep original" chip (value `null`) reuses the source job's stored value; any
 * other chip sets that field as an override. Purely presentational — selection
 * state is owned by the parent (immutable updates).
 */

export interface ChipOption {
  id: string;
  label: string;
}

export interface OptionChipsProps {
  options: readonly ChipOption[];
  /** Selected option id, or null for "keep original". */
  value: string | null;
  onChange: (id: string | null) => void;
  /** Label for the leading keep-original chip. */
  keepLabel?: string;
  loading?: boolean;
  disabled?: boolean;
  /** Shown when there are no options and we are not loading. */
  emptyText?: string;
}

export function OptionChips({
  options,
  value,
  onChange,
  keepLabel = "Keep original",
  loading = false,
  disabled = false,
  emptyText = "Nothing to choose from.",
}: Readonly<OptionChipsProps>) {
  if (loading) {
    return (
      <View style={styles.loadingRow}>
        <ActivityIndicator color="#E6C76A" />
        <Text style={styles.meta}>Loading…</Text>
      </View>
    );
  }

  return (
    <View style={styles.wrap}>
      <Chip
        label={keepLabel}
        active={value === null}
        disabled={disabled}
        onPress={() => onChange(null)}
      />
      {options.length === 0 ? (
        <Text style={styles.meta}>{emptyText}</Text>
      ) : (
        options.map((opt) => (
          <Chip
            key={opt.id}
            label={opt.label}
            active={opt.id === value}
            disabled={disabled}
            onPress={() => onChange(opt.id)}
          />
        ))
      )}
    </View>
  );
}

interface ChipProps {
  label: string;
  active: boolean;
  disabled: boolean;
  onPress: () => void;
}

function Chip({ label, active, disabled, onPress }: Readonly<ChipProps>) {
  return (
    <Pressable
      style={[styles.chip, active && styles.chipActive, disabled && styles.chipDisabled]}
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityState={{ selected: active, disabled }}
    >
      <Text style={[styles.chipText, active && styles.chipTextActive]}>
        {label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  wrap: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  loadingRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  chip: {
    backgroundColor: "#0f0f10",
    borderColor: "#27272a",
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  chipActive: { backgroundColor: "#E6C76A", borderColor: "#E6C76A" },
  chipDisabled: { opacity: 0.5 },
  chipText: { color: "#ece9e1" },
  chipTextActive: { color: "#0f0f10", fontWeight: "700" },
  meta: { color: "#6f6c65", fontSize: 13 },
});
