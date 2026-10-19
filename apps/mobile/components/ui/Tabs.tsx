/**
 * Tabs primitive — a horizontal row of tab items. Controlled component.
 * No emoji. Explicit types.
 */

import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  type StyleProp,
  type ViewStyle,
} from "react-native";

import { colors } from "@/components/me/theme";
import { radius, spacing, weight } from "@/src/shared/theme";

export interface TabItem<T extends string = string> {
  id: T;
  label: string;
  badge?: number | string;
}

export interface TabsProps<T extends string = string> {
  items: readonly TabItem<T>[];
  value: T;
  onChange: (id: T) => void;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
  /** Render as a scrollable row instead of evenly-distributed. */
  scrollable?: boolean;
}

export function Tabs<T extends string = string>({
  items,
  value,
  onChange,
  disabled = false,
  style,
  scrollable = true,
}: TabsProps<T>): React.JSX.Element {
  const content = items.map((item) => {
    const active = item.id === value;
    return (
      <Pressable
        key={item.id}
        onPress={() => !disabled && onChange(item.id)}
        accessibilityRole="tab"
        accessibilityState={{ selected: active, disabled }}
        style={[
          styles.tab,
          active && styles.tabActive,
          disabled && styles.tabDisabled,
        ]}
      >
        <Text style={[styles.label, active && styles.labelActive]}>
          {item.label}
          {item.badge !== undefined ? ` (${item.badge})` : ""}
        </Text>
      </Pressable>
    );
  });

  if (scrollable) {
    return (
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={[styles.row, style]}
        accessibilityRole="tablist"
      >
        {content}
      </ScrollView>
    );
  }

  return (
    <ScrollView
      horizontal={false}
      scrollEnabled={false}
      contentContainerStyle={[styles.rowFixed, style]}
      accessibilityRole="tablist"
    >
      {content}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    gap: spacing.sm,
    paddingVertical: 2,
  },
  rowFixed: {
    flexDirection: "row",
    gap: spacing.xs,
  },
  tab: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs + 2,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
  },
  tabActive: {
    backgroundColor: colors.accent,
    borderColor: colors.accent,
  },
  tabDisabled: { opacity: 0.5 },
  label: {
    color: colors.textSecondary,
    fontSize: 13,
    fontWeight: weight.bold,
  },
  labelActive: { color: colors.bg },
});
