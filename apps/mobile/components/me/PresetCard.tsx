/**
 * A single saved-preset row with a delete affordance. Presentational; the
 * parent owns the delete network call and optimistic list update.
 */

import { useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import type { Preset } from "@/lib/types";

import { colors } from "./theme";

interface PresetCardProps {
  preset: Preset;
  onDelete: (id: string) => Promise<void>;
}

export function PresetCard({ preset, onDelete }: PresetCardProps) {
  const [deleting, setDeleting] = useState(false);

  const configKeys = Object.keys(preset.config ?? {});
  const summary =
    configKeys.length > 0
      ? `${configKeys.length} setting${configKeys.length === 1 ? "" : "s"}: ${configKeys
          .slice(0, 4)
          .join(", ")}`
      : "No settings saved";

  // A brand kit shared to a workspace is visible to every member. Mirror the
  // backend's `shared` flag, falling back to the presence of `workspace_id`.
  const isShared = preset.shared === true || !!preset.workspace_id;

  const onPress = async () => {
    setDeleting(true);
    try {
      await onDelete(preset.id);
    } finally {
      // If deletion succeeded the card unmounts; on failure we re-enable it.
      setDeleting(false);
    }
  };

  return (
    <View style={styles.card}>
      <View style={styles.body}>
        <View style={styles.nameRow}>
          <Text style={styles.name} numberOfLines={1}>
            {preset.name}
          </Text>
          {isShared ? (
            <View style={styles.badge} accessibilityLabel="Shared to team">
              <Text style={styles.badgeText}>Shared</Text>
            </View>
          ) : null}
        </View>
        <Text style={styles.summary} numberOfLines={2}>
          {summary}
        </Text>
      </View>
      <Pressable
        style={styles.delete}
        onPress={onPress}
        disabled={deleting}
        hitSlop={8}
      >
        {deleting ? (
          <ActivityIndicator color={colors.error} size="small" />
        ) : (
          <Text style={styles.deleteText}>Delete</Text>
        )}
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
  },
  body: { flex: 1, gap: 4 },
  nameRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  name: { color: colors.textPrimary, fontSize: 15, fontWeight: "700", flexShrink: 1 },
  badge: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.primary,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  badgeText: {
    color: colors.accent,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 0.5,
  },
  summary: { color: colors.muted, fontSize: 12 },
  delete: { paddingHorizontal: 10, paddingVertical: 6 },
  deleteText: { color: colors.error, fontWeight: "600", fontSize: 14 },
});
