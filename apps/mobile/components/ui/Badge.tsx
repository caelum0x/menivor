/**
 * Badge primitive — small count or label indicator.
 * No emoji. Explicit types.
 */

import {
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type ViewStyle,
} from "react-native";

import { colors } from "@/components/me/theme";
import { radius } from "@/src/shared/theme";

export type BadgeVariant = "accent" | "success" | "danger" | "neutral";

export interface BadgeProps {
  label: string | number;
  variant?: BadgeVariant;
  style?: StyleProp<ViewStyle>;
}

const variantColor: Record<BadgeVariant, { bg: string; text: string }> = {
  accent: { bg: colors.accent, text: colors.bg },
  success: { bg: colors.success, text: "#fff" },
  danger: { bg: colors.error, text: "#fff" },
  neutral: { bg: colors.cardAlt, text: colors.textSecondary },
};

export function Badge({
  label,
  variant = "neutral",
  style,
}: BadgeProps): React.JSX.Element {
  const { bg, text } = variantColor[variant];
  return (
    <View style={[styles.badge, { backgroundColor: bg }, style]}>
      <Text style={[styles.text, { color: text }]}>{String(label)}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: radius.pill,
    alignSelf: "flex-start",
  },
  text: {
    fontSize: 11,
    fontWeight: "700",
    lineHeight: 14,
  },
});
