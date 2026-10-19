/**
 * A single row in the notification center: kind glyph, title, body, relative
 * time, and an unread dot. Tapping calls `onPress(notification)` — the screen
 * decides to mark it read and (when `data.job_id` is present) deep-link to the
 * job. Read rows are visually dimmed. Pure/presentational.
 */

import { memo } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import type { Notification } from "@/lib/types";
import { colors } from "@/components/me/theme";
import { Icon } from "@/components/ui/Icon";
import {
  formatRelativeTime,
  jobIdFromNotification,
  kindMeta,
} from "./notification-meta";

interface NotificationItemProps {
  notification: Notification;
  onPress: (notification: Notification) => void;
}

function NotificationItemBase({ notification, onPress }: NotificationItemProps) {
  const meta = kindMeta(notification.kind);
  const time = formatRelativeTime(notification.created_at);
  const hasJob = jobIdFromNotification(notification) !== null;
  const unread = !notification.read;

  return (
    <Pressable
      onPress={() => onPress(notification)}
      style={({ pressed }) => [
        styles.card,
        unread ? styles.cardUnread : null,
        pressed ? styles.cardPressed : null,
      ]}
      accessibilityRole="button"
      accessibilityLabel={`${meta.label}: ${notification.title}${
        unread ? ", unread" : ""
      }`}
    >
      <View style={styles.glyphWrap}>
        <Icon name={meta.icon} size={18} color={meta.color} />
      </View>

      <View style={styles.body}>
        <View style={styles.headerRow}>
          <Text
            style={[styles.title, unread ? styles.titleUnread : null]}
            numberOfLines={1}
          >
            {notification.title}
          </Text>
          {time ? <Text style={styles.time}>{time}</Text> : null}
        </View>

        {notification.body ? (
          <Text style={styles.text} numberOfLines={3}>
            {notification.body}
          </Text>
        ) : null}

        {hasJob ? <Text style={styles.link}>View job</Text> : null}
      </View>

      {unread ? (
        <View style={[styles.dot, { backgroundColor: meta.color }]} />
      ) : null}
    </Pressable>
  );
}

export const NotificationItem = memo(NotificationItemBase);

const styles = StyleSheet.create({
  card: {
    flexDirection: "row",
    gap: 12,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    alignItems: "flex-start",
  },
  cardUnread: { backgroundColor: colors.cardAlt },
  cardPressed: { opacity: 0.7 },
  glyphWrap: {
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: colors.bg,
    alignItems: "center",
    justifyContent: "center",
  },
  glyph: { fontSize: 18 },
  body: { flex: 1, gap: 4 },
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  title: { color: colors.textSecondary, fontSize: 15, fontWeight: "600", flex: 1 },
  titleUnread: { color: colors.textPrimary, fontWeight: "700" },
  time: { color: colors.muted, fontSize: 12 },
  text: { color: colors.muted, fontSize: 13, lineHeight: 18 },
  link: { color: colors.accent, fontSize: 13, fontWeight: "600", marginTop: 2 },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginTop: 6,
  },
});
