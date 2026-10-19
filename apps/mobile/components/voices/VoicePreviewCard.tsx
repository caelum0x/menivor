/**
 * VoicePreviewCard — one catalog voice (GET /voices) row with a play/pause
 * preview control, its category + descriptive labels, and an optional "Use"
 * action. Presentational: the parent owns playback state (via useAudioPreview)
 * and the "use" navigation.
 */

import { memo } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import type { Voice } from "@/lib/types";

import { colors } from "@/components/me/theme";

interface VoicePreviewCardProps {
  voice: Voice;
  playing: boolean;
  loading: boolean;
  hasPreview: boolean;
  onTogglePreview: () => void;
  onUse?: () => void;
}

/** Renders up to three human-readable label chips (accent, gender, age…). */
function labelChips(labels?: Record<string, string>): string[] {
  if (!labels) return [];
  return Object.values(labels)
    .map((v) => (typeof v === "string" ? v.trim() : ""))
    .filter((v) => v.length > 0)
    .slice(0, 3);
}

function VoicePreviewCardImpl({
  voice,
  playing,
  loading,
  hasPreview,
  onTogglePreview,
  onUse,
}: VoicePreviewCardProps) {
  const name = (voice.name || voice.voice_id).trim();
  const chips = labelChips(voice.labels);
  const category = (voice.category || "").trim();

  return (
    <View style={styles.card}>
      <Pressable
        style={[styles.play, playing && styles.playActive]}
        onPress={onTogglePreview}
        disabled={loading || !hasPreview}
        accessibilityRole="button"
        accessibilityState={{ disabled: loading || !hasPreview, selected: playing }}
        accessibilityLabel={playing ? `Pause ${name}` : `Play ${name}`}
        hitSlop={8}
      >
        {loading ? (
          <ActivityIndicator color={colors.bg} size="small" />
        ) : (
          <Text style={[styles.playText, playing && styles.playTextActive]}>
            {hasPreview ? (playing ? "Pause" : "Play") : "—"}
          </Text>
        )}
      </Pressable>

      <View style={styles.body}>
        <Text style={styles.name} numberOfLines={1}>
          {name}
        </Text>
        <View style={styles.metaRow}>
          {category ? (
            <View style={styles.catBadge}>
              <Text style={styles.catText}>{category}</Text>
            </View>
          ) : null}
          {chips.length > 0 ? (
            <Text style={styles.labels} numberOfLines={1}>
              {chips.join(" · ")}
            </Text>
          ) : null}
        </View>
      </View>

      {onUse ? (
        <Pressable
          style={styles.use}
          onPress={onUse}
          accessibilityRole="button"
          hitSlop={8}
        >
          <Text style={styles.useText}>Use</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

export const VoicePreviewCard = memo(VoicePreviewCardImpl);

const styles = StyleSheet.create({
  card: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
  },
  play: {
    width: 56,
    height: 40,
    borderRadius: 8,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
  },
  playActive: { backgroundColor: colors.textPrimary },
  playText: { color: colors.bg, fontSize: 13, fontWeight: "700" },
  playTextActive: { color: colors.bg },
  body: { flex: 1, gap: 4 },
  name: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  metaRow: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" },
  catBadge: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  catText: { color: colors.textSecondary, fontSize: 11, fontWeight: "600" },
  labels: { color: colors.muted, fontSize: 12, flexShrink: 1 },
  use: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  useText: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
});
