/**
 * Chip primitive — small pill tag for filters, labels, or selection.
 */

import {
  Pressable,
  StyleSheet,
  Text,
  type StyleProp,
  type ViewStyle,
} from "react-native";

import { colors } from "@/components/me/theme";
import { radius, spacing } from "@/src/shared/theme";

export interface ChipProps {
  label: string;
  active?: boolean;
  onPress?: () => void;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
}

export function Chip({
  label,
  active = false,
  onPress,
  disabled = false,
  style,
}: ChipProps): React.JSX.Element {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      accessibilityRole={onPress ? "button" : "none"}
      accessibilityState={{ selected: active, disabled }}
      style={[
        styles.chip,
        active && styles.chipActive,
        disabled && styles.chipDisabled,
        style,
      ]}
    >
      <Text style={[styles.label, active && styles.labelActive]}>
        {label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  chip: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs + 2,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
  },
  chipActive: {
    backgroundColor: colors.accent,
    borderColor: colors.accent,
  },
  chipDisabled: { opacity: 0.5 },
  label: {
    color: colors.textSecondary,
    fontSize: 13,
    fontWeight: "700",
  },
  labelActive: { color: colors.bg },
});
