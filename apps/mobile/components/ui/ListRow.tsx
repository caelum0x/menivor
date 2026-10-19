/**
 * ListRow primitive — a pressable row with title, optional subtitle and chevron.
 * Used for navigation lists (settings, menus). No emoji.
 */

import type { ReactNode } from "react";
import {
  Pressable,
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type ViewStyle,
} from "react-native";

import { colors } from "@/components/me/theme";
import { radius, spacing } from "@/src/shared/theme";
import { Icon } from "./Icon";

export interface ListRowProps {
  title: string;
  subtitle?: string;
  /** Optional leading element (icon, avatar, badge). */
  leading?: ReactNode;
  /** Optional trailing element (replaces default chevron when set). */
  trailing?: ReactNode;
  /** Show the default chevron. Defaults true when onPress is provided. */
  showChevron?: boolean;
  onPress?: () => void;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
  /** Apply highlighted border. */
  highlighted?: boolean;
}

export function ListRow({
  title,
  subtitle,
  leading,
  trailing,
  showChevron,
  onPress,
  disabled,
  style,
  highlighted = false,
}: ListRowProps): React.JSX.Element {
  const chevron = showChevron ?? !!onPress;

  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      accessibilityRole={onPress ? "button" : "none"}
      accessibilityState={{ disabled: !!disabled }}
      style={[
        styles.row,
        highlighted && styles.highlighted,
        disabled && styles.disabled,
        style,
      ]}
    >
      {leading ? <View style={styles.leading}>{leading}</View> : null}
      <View style={styles.body}>
        <Text style={styles.title}>{title}</Text>
        {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
      </View>
      {trailing ?? null}
      {!trailing && chevron ? (
        <Icon name="chevron-forward" style={styles.chevron} />
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.lg,
    padding: spacing.lg,
  },
  highlighted: { borderColor: colors.accent },
  disabled: { opacity: 0.5 },
  leading: { flexShrink: 0 },
  body: { flex: 1, gap: 4 },
  title: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  subtitle: { color: colors.muted, fontSize: 12 },
  chevron: { color: colors.muted, fontSize: 22, fontWeight: "700" },
});
