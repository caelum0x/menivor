/**
 * Header primitive — section title + optional subtitle + optional action slot.
 * Renders consistent section/page headers throughout the app. No emoji.
 */

import type { ReactNode } from "react";
import {
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type ViewStyle,
} from "react-native";

import { colors } from "@/components/me/theme";
import { spacing, typeScale, weight } from "@/src/shared/theme";

export interface HeaderProps {
  title: string;
  subtitle?: string;
  /** Optional right-side element (e.g. a Button, Chip, or icon). */
  action?: ReactNode;
  style?: StyleProp<ViewStyle>;
  /** Reduce font size for sub-section headers. */
  compact?: boolean;
}

export function Header({
  title,
  subtitle,
  action,
  style,
  compact = false,
}: HeaderProps): React.JSX.Element {
  return (
    <View style={[styles.row, style]}>
      <View style={styles.body}>
        <Text style={compact ? styles.titleCompact : styles.title}>{title}</Text>
        {subtitle ? (
          <Text style={styles.subtitle}>{subtitle}</Text>
        ) : null}
      </View>
      {action ? <View style={styles.action}>{action}</View> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.md,
    marginBottom: spacing.md,
  },
  body: { flex: 1, gap: 2 },
  title: {
    color: colors.textPrimary,
    fontSize: typeScale.heading,
    fontWeight: weight.black,
  },
  titleCompact: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: weight.bold,
    letterSpacing: 1.2,
    textTransform: "uppercase",
  },
  subtitle: {
    color: colors.textSecondary,
    fontSize: 13,
  },
  action: { flexShrink: 0 },
});
