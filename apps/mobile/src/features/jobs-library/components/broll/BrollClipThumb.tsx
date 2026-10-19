import { useState } from "react";
import { Image, Pressable, StyleSheet, Text, View } from "react-native";

import { toDisplayUrl } from "@/src/shared/media";
import type { BrollClip } from "@/lib/types";

import { sourceLabel } from "./broll-sources";

export interface BrollClipThumbProps {
  clip: BrollClip;
  /** True when this clip is the chosen intro cutaway. */
  introSelected: boolean;
  /** True when this clip is the chosen outro cutaway. */
  outroSelected: boolean;
  /** Disables the pick buttons (e.g. while a suggest call is in flight). */
  disabled?: boolean;
  /** Toggle this clip as the intro cutaway. */
  onToggleIntro: () => void;
  /** Toggle this clip as the outro cutaway. */
  onToggleOutro: () => void;
}

/** Formats a jobs-library clip duration as a short "3s" label, when known. */
function durationLabel(duration?: number): string | null {
  if (typeof duration !== "number" || !Number.isFinite(duration) || duration <= 0) {
    return null;
  }
  return `${Math.round(duration)}s`;
}

/**
 * One suggested B-roll clip rendered as a vertical thumbnail card with two
 * toggle buttons to assign it as the muted Intro and/or Outro cutaway. The
 * thumbnail degrades to a labelled placeholder when no usable image URL is
 * available (a bare R2 key can't be resolved on-device).
 */
export function BrollClipThumb({
  clip,
  introSelected,
  outroSelected,
  disabled = false,
  onToggleIntro,
  onToggleOutro,
}: Readonly<BrollClipThumbProps>) {
  const [imageErrored, setImageErrored] = useState(false);
  const thumbUrl = toDisplayUrl(clip.thumbnail_url);
  const showImage = Boolean(thumbUrl) && !imageErrored;
  const duration = durationLabel(clip.duration_s);
  const isIntro = introSelected;
  const isOutro = outroSelected;

  return (
    <View style={styles.card}>
      <View style={styles.thumbWrap}>
        {showImage ? (
          <Image
            source={{ uri: thumbUrl }}
            style={styles.thumb}
            resizeMode="cover"
            accessibilityLabel="B-roll clip thumbnail"
            onError={() => setImageErrored(true)}
          />
        ) : (
          <View style={[styles.thumb, styles.placeholder]}>
            <Text style={styles.placeholderText}>
              {sourceLabel(String(clip.source))}
            </Text>
          </View>
        )}
        {duration ? (
          <View style={styles.durationBadge}>
            <Text style={styles.durationText}>{duration}</Text>
          </View>
        ) : null}
      </View>

      <View style={styles.actions}>
        <Pressable
          style={[styles.pick, isIntro && styles.pickActive, disabled && styles.disabled]}
          onPress={onToggleIntro}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityLabel="Use this clip as the intro cutaway"
          accessibilityState={{ selected: isIntro, disabled }}
        >
          <Text style={[styles.pickText, isIntro && styles.pickTextActive]}>
            Intro
          </Text>
        </Pressable>
        <Pressable
          style={[styles.pick, isOutro && styles.pickActive, disabled && styles.disabled]}
          onPress={onToggleOutro}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityLabel="Use this clip as the outro cutaway"
          accessibilityState={{ selected: isOutro, disabled }}
        >
          <Text style={[styles.pickText, isOutro && styles.pickTextActive]}>
            Outro
          </Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { width: 132, gap: 8 },
  thumbWrap: { position: "relative" },
  thumb: {
    width: 132,
    aspectRatio: 9 / 16,
    borderRadius: 12,
    backgroundColor: "#000000",
  },
  placeholder: {
    alignItems: "center",
    justifyContent: "center",
    borderColor: "#27272a",
    borderWidth: 1,
    backgroundColor: "#0f0f10",
  },
  placeholderText: { color: "#6f6c65", fontSize: 12, fontWeight: "600" },
  durationBadge: {
    position: "absolute",
    right: 6,
    bottom: 6,
    backgroundColor: "rgba(0,0,0,0.7)",
    borderRadius: 6,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  durationText: { color: "#ece9e1", fontSize: 11, fontWeight: "600" },
  actions: { flexDirection: "row", gap: 6 },
  pick: {
    flex: 1,
    backgroundColor: "#0f0f10",
    borderColor: "#27272a",
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 8,
    alignItems: "center",
  },
  pickActive: { borderColor: "#E6C76A", backgroundColor: "#2a2416" },
  pickText: { color: "#ece9e1", fontSize: 13, fontWeight: "600" },
  pickTextActive: { color: "#E6C76A" },
  disabled: { opacity: 0.5 },
});
