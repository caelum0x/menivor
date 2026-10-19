/**
 * Card primitive — themed container with border, background and subtle soft
 * depth (glass edge highlight + soft shadow).
 */

import type { ReactNode } from "react";
import {
  StyleSheet,
  View,
  type StyleProp,
  type ViewStyle,
} from "react-native";

import { colors } from "@/components/me/theme";
import { radius, spacing } from "@/src/shared/theme";
import { softCardDepth } from "@/src/shared/theme/surface";

export interface CardProps {
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
  /** Tighter padding variant for compact contexts. */
  compact?: boolean;
  /** Highlight the card border with the accent color. */
  highlighted?: boolean;
}

export function Card({
  children,
  style,
  compact = false,
  highlighted = false,
}: CardProps): React.JSX.Element {
  return (
    <View
      style={[
        styles.card,
        softCardDepth,
        compact && styles.compact,
        highlighted && styles.highlighted,
        style,
      ]}
    >
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.lg,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  compact: {
    padding: spacing.md,
    gap: spacing.xs,
  },
  highlighted: {
    borderColor: colors.accent,
  },
});
