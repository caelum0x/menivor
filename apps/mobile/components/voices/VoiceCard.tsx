/**
 * A single cloned brand voice row with a delete affordance. Presentational; the
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

import type { UserVoice } from "@/lib/types";

import { colors } from "@/components/me/theme";

interface VoiceCardProps {
  voice: UserVoice;
  onDelete: (id: string) => Promise<void>;
}

export function VoiceCard({ voice, onDelete }: VoiceCardProps) {
  const [deleting, setDeleting] = useState(false);

  const onPress = async () => {
    setDeleting(true);
    try {
      await onDelete(voice.id);
    } finally {
      // On success the card unmounts; on failure we re-enable it.
      setDeleting(false);
    }
  };

  const statusLabel =
    voice.status && voice.status !== "ready" ? voice.status : "Ready";

  return (
    <View style={styles.card}>
      <View style={styles.body}>
        <Text style={styles.name} numberOfLines={1}>
          {voice.name}
        </Text>
        <Text style={styles.selector} numberOfLines={1}>
          {voice.voice_id}
        </Text>
      </View>
      <View style={styles.status}>
        <Text style={styles.statusText}>{statusLabel}</Text>
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
    gap: 10,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
  },
  body: { flex: 1, gap: 4 },
  name: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  selector: { color: colors.muted, fontSize: 12 },
  status: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  statusText: { color: colors.textSecondary, fontSize: 11, fontWeight: "600" },
  delete: { paddingHorizontal: 10, paddingVertical: 6 },
  deleteText: { color: colors.error, fontWeight: "600", fontSize: 14 },
});
