/**
 * Bell button with an overlaid unread badge, for the header / Me tab. Fetches
 * its own unread count (via {@link useUnreadCount}, refreshed on focus) and taps
 * through to the notification center. Self-contained so it can be dropped into a
 * navigator's `headerRight` or rendered inline.
 */

import { Pressable, StyleSheet, View } from "react-native";

import { useRouter } from "expo-router";

import { colors } from "@/components/me/theme";
import { UnreadBadge } from "./UnreadBadge";
import { useUnreadCount } from "./useUnreadCount";

interface NotificationBellProps {
  /** Extra horizontal padding, useful when placed in a header. */
  compact?: boolean;
}

export function NotificationBell({ compact = false }: NotificationBellProps) {
  const router = useRouter();
  const { count } = useUnreadCount();

  return (
    <Pressable
      onPress={() => router.push("/notifications")}
      hitSlop={10}
      accessibilityRole="button"
      accessibilityLabel={
        count > 0
          ? `Notifications, ${count} unread`
          : "Notifications"
      }
      style={[styles.button, compact ? styles.compact : null]}
    >
      <View style={styles.bellIcon}>
        <View style={styles.bellDome} />
        <View style={styles.bellBase} />
      </View>
      {count > 0 ? (
        <View style={styles.badgeAnchor}>
          <UnreadBadge count={count} />
        </View>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    width: 40,
    height: 40,
    alignItems: "center",
    justifyContent: "center",
  },
  compact: { marginRight: 8 },
  bellIcon: {
    width: 20,
    height: 20,
    alignItems: "center",
    justifyContent: "flex-end",
  },
  bellDome: {
    width: 14,
    height: 12,
    borderTopLeftRadius: 7,
    borderTopRightRadius: 7,
    borderWidth: 2,
    borderBottomWidth: 0,
    borderColor: colors.textPrimary,
  },
  bellBase: {
    width: 8,
    height: 2,
    backgroundColor: colors.textPrimary,
    borderRadius: 1,
  },
  badgeAnchor: {
    position: "absolute",
    top: 2,
    right: 2,
  },
});
