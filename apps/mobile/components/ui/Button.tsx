/**
 * Button primitive — primary, secondary, ghost, and destructive variants.
 * All themed, no emoji, explicit typed props.
 */

import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  type PressableProps,
  type StyleProp,
  type ViewStyle,
} from "react-native";

import { colors } from "@/components/me/theme";
import { radius, spacing, weight } from "@/src/shared/theme";
import { softButtonDepth } from "@/src/shared/theme/surface";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "destructive";
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps extends Omit<PressableProps, "style" | "children"> {
  label: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  style?: StyleProp<ViewStyle>;
}

const variantStyles: Record<ButtonVariant, { container: object; text: object }> = {
  primary: {
    container: { backgroundColor: colors.accent, borderColor: colors.accent },
    text: { color: colors.bg, fontWeight: weight.bold },
  },
  secondary: {
    container: { backgroundColor: colors.card, borderColor: colors.border },
    text: { color: colors.textPrimary, fontWeight: weight.semibold },
  },
  ghost: {
    container: { backgroundColor: "transparent", borderColor: "transparent" },
    text: { color: colors.textSecondary, fontWeight: weight.semibold },
  },
  destructive: {
    container: { backgroundColor: "transparent", borderColor: colors.error },
    text: { color: colors.error, fontWeight: weight.semibold },
  },
};

const sizeStyles: Record<ButtonSize, { container: object; text: object }> = {
  sm: {
    container: { paddingHorizontal: spacing.md, paddingVertical: spacing.xs + 2, borderRadius: radius.md },
    text: { fontSize: 13 },
  },
  md: {
    container: { paddingHorizontal: spacing.lg, paddingVertical: spacing.sm + 2, borderRadius: radius.md },
    text: { fontSize: 15 },
  },
  lg: {
    container: { paddingHorizontal: spacing.xl, paddingVertical: spacing.md, borderRadius: radius.lg },
    text: { fontSize: 16 },
  },
};

export function Button({
  label,
  variant = "primary",
  size = "md",
  loading = false,
  disabled,
  style,
  ...rest
}: ButtonProps): React.JSX.Element {
  const v = variantStyles[variant];
  const s = sizeStyles[size];
  const isDisabled = disabled || loading;

  return (
    <Pressable
      {...rest}
      disabled={isDisabled}
      accessibilityRole="button"
      accessibilityState={{ disabled: !!isDisabled, busy: loading }}
      style={({ pressed }) => [
        styles.base,
        v.container,
        s.container,
        // The primary action is a soft raised control that sinks when pressed.
        variant === "primary" && !isDisabled && softButtonDepth(colors.accent, pressed),
        isDisabled && styles.disabled,
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator
          size="small"
          color={variant === "primary" ? colors.bg : colors.textSecondary}
        />
      ) : (
        <Text style={[styles.text, v.text, s.text]}>{label}</Text>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    borderWidth: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
  },
  text: {
    textAlign: "center",
  },
  disabled: { opacity: 0.5 },
});
