/**
 * Segmented control primitive — a fixed-width set of mutually exclusive options.
 * Renders as an even-width button group, ideal for 2-4 options.
 * No emoji. Explicit types.
 */

import {
  Pressable,
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type ViewStyle,
} from "react-native";

import { colors } from "@/components/me/theme";
import { radius, spacing, weight } from "@/src/shared/theme";

export interface SegmentedItem<T extends string = string> {
  id: T;
  label: string;
}

export interface SegmentedProps<T extends string = string> {
  items: readonly SegmentedItem<T>[];
  value: T;
  onChange: (id: T) => void;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
}

export function Segmented<T extends string = string>({
  items,
  value,
  onChange,
  disabled = false,
  style,
}: SegmentedProps<T>): React.JSX.Element {
  return (
    <View style={[styles.container, style]} accessibilityRole="radiogroup">
      {items.map((item, index) => {
        const active = item.id === value;
        const first = index === 0;
        const last = index === items.length - 1;
        return (
          <Pressable
            key={item.id}
            onPress={() => !disabled && onChange(item.id)}
            accessibilityRole="radio"
            accessibilityState={{ checked: active, disabled }}
            style={[
              styles.segment,
              first && styles.first,
              last && styles.last,
              active && styles.segmentActive,
              disabled && styles.segmentDisabled,
            ]}
          >
            <Text style={[styles.label, active && styles.labelActive]}>
              {item.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: "row",
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    overflow: "hidden",
    backgroundColor: colors.card,
  },
  segment: {
    flex: 1,
    paddingVertical: spacing.sm,
    alignItems: "center",
    justifyContent: "center",
    borderRightWidth: 1,
    borderRightColor: colors.border,
  },
  first: { borderTopLeftRadius: radius.md - 1, borderBottomLeftRadius: radius.md - 1 },
  last: { borderRightWidth: 0, borderTopRightRadius: radius.md - 1, borderBottomRightRadius: radius.md - 1 },
  segmentActive: { backgroundColor: colors.accent },
  segmentDisabled: { opacity: 0.5 },
  label: {
    color: colors.textSecondary,
    fontSize: 13,
    fontWeight: weight.bold,
  },
  labelActive: { color: colors.bg },
});
