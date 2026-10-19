/**
 * Presentational body of a SPARK concept: title, hook, angle, script beats and
 * a row of suggestion tags (format / layout / caption style / language /
 * duration). Shared by {@link IdeaCard} (generated) and the saved-idea card so
 * both render a concept identically.
 */

import { StyleSheet, Text, View } from "react-native";

import type { Idea } from "@/lib/types";

import { colors } from "@/components/me/theme";

interface IdeaBodyProps {
  idea: Idea;
}

/** Human-readable duration tag, e.g. "30s"; omitted when unknown/invalid. */
function durationTag(seconds: number | null | undefined): string | null {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds <= 0) {
    return null;
  }
  return `${Math.round(seconds)}s`;
}

export function IdeaBody({ idea }: IdeaBodyProps) {
  const beats = Array.isArray(idea.script_outline) ? idea.script_outline : [];
  const tags: string[] = [
    idea.format,
    idea.suggested_layout,
    idea.suggested_caption_style,
    idea.language,
    durationTag(idea.est_duration_s),
  ]
    .filter((t): t is string => typeof t === "string" && t.trim().length > 0)
    .map((t) => t.trim());

  return (
    <View style={styles.body}>
      {idea.title ? <Text style={styles.title}>{idea.title}</Text> : null}
      {idea.hook ? <Text style={styles.hook}>“{idea.hook}”</Text> : null}
      {idea.angle ? <Text style={styles.angle}>{idea.angle}</Text> : null}

      {beats.length > 0 ? (
        <View style={styles.beats}>
          {beats.map((beat, i) => (
            <View key={i} style={styles.beatRow}>
              <Text style={styles.beatNum}>{i + 1}</Text>
              <Text style={styles.beatText}>{beat}</Text>
            </View>
          ))}
        </View>
      ) : null}

      {tags.length > 0 ? (
        <View style={styles.tags}>
          {tags.map((tag, i) => (
            <View key={`${tag}-${i}`} style={styles.tag}>
              <Text style={styles.tagText}>{tag}</Text>
            </View>
          ))}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  body: { gap: 8 },
  title: { color: colors.textPrimary, fontSize: 17, fontWeight: "800" },
  hook: {
    color: colors.accent,
    fontSize: 15,
    fontWeight: "600",
    fontStyle: "italic",
  },
  angle: { color: colors.textSecondary, fontSize: 14, lineHeight: 20 },
  beats: { gap: 6, marginTop: 2 },
  beatRow: { flexDirection: "row", gap: 8, alignItems: "flex-start" },
  beatNum: {
    color: colors.muted,
    fontSize: 13,
    fontWeight: "700",
    width: 16,
    textAlign: "center",
  },
  beatText: { color: colors.textSecondary, fontSize: 14, flex: 1, lineHeight: 20 },
  tags: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 2 },
  tag: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  tagText: { color: colors.muted, fontSize: 12, fontWeight: "600" },
});
