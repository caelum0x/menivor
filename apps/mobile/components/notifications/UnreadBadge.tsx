/**
 * Presentational unread-count pill. Renders nothing when `count <= 0`, a small
 * accented badge otherwise (capped at "99+"). Pure — it takes the count as a
 * prop so it can decorate any surface (the header bell, a Me-tab row, etc.)
 * without owning any fetching.
 */

import { StyleSheet, Text, View } from "react-native";

import { colors } from "@/components/me/theme";

interface UnreadBadgeProps {
  count: number;
  /** Optional accessibility noun, e.g. "unread notifications" (default). */
  label?: string;
}

export function UnreadBadge({ count, label = "unread notifications" }: UnreadBadgeProps) {
  if (!Number.isFinite(count) || count <= 0) return null;

  const display = count > 99 ? "99+" : String(count);

  return (
    <View
      style={styles.badge}
      accessibilityRole="text"
      accessibilityLabel={`${count} ${label}`}
    >
      <Text style={styles.text} allowFontScaling={false}>
        {display}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    minWidth: 18,
    height: 18,
    borderRadius: 9,
    paddingHorizontal: 5,
    backgroundColor: colors.error,
    alignItems: "center",
    justifyContent: "center",
  },
  text: {
    color: "#ffffff",
    fontSize: 11,
    fontWeight: "800",
    lineHeight: 14,
  },
});
