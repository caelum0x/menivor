/**
 * Reel-create horizontal cards for the burned-in karaoke caption style,
 * driven by GET /catalog/caption-styles. Each card shows a mini caption preview
 * plus the primary/secondary colour swatches (ASS colours converted to CSS).
 * Emits the backend caption-style id upward. Handles loading, error, and empty
 * states. Mirrors web/components/wizard/CaptionStylePicker.tsx.
 */
import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { ApiError, listCaptionStyles } from "@/lib/api";
import type { CaptionStyle } from "@/lib/types";

import { assColorToCss } from "./caption-colors";

interface CaptionStylePickerProps {
  /** Selected caption-style id, or null when none chosen yet. */
  value: string | null;
  onSelect: (captionStyle: string) => void;
  token?: string;
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; styles: CaptionStyle[] };

function CaptionPreview({ style }: { style: CaptionStyle }) {
  const spoken = assColorToCss(style.primary);
  const upcoming = assColorToCss(style.secondary, spoken);
  const words: readonly [string, string, string] = ["This", "is", "how"];
  return (
    <View style={styles.preview}>
      {words.map((word, i) => (
        <Text
          key={word}
          style={[styles.previewWord, { color: i === 0 ? spoken : upcoming }]}
        >
          {word}
        </Text>
      ))}
    </View>
  );
}

function ColorSwatches({ style }: { style: CaptionStyle }) {
  const primary = assColorToCss(style.primary);
  const secondary = assColorToCss(style.secondary, primary);
  return (
    <View style={styles.swatches}>
      <View style={[styles.swatch, { backgroundColor: primary }]} />
      <View style={[styles.swatch, { backgroundColor: secondary }]} />
    </View>
  );
}

export function CaptionStylePicker({
  value,
  onSelect,
  token,
}: CaptionStylePickerProps) {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  const load = useCallback(async () => {
    setState({ status: "loading" });
    try {
      const styles = await listCaptionStyles({ token });
      setState({ status: "ready", styles });
    } catch (err) {
      setState({
        status: "error",
        message:
          err instanceof ApiError
            ? err.message
            : "Could not load caption styles. Please try again.",
      });
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  if (state.status === "loading") {
    return (
      <View style={styles.center}>
        <ActivityIndicator color="#E6C76A" />
      </View>
    );
  }

  if (state.status === "error") {
    return (
      <View style={styles.center}>
        <Text style={styles.error}>{state.message}</Text>
        <Pressable style={styles.retry} onPress={() => void load()}>
          <Text style={styles.retryText}>Retry</Text>
        </Pressable>
      </View>
    );
  }

  if (state.styles.length === 0) {
    return (
      <Text style={styles.empty}>No caption styles are available yet.</Text>
    );
  }

  return (
    <FlatList
      horizontal
      data={state.styles}
      keyExtractor={(item) => item.id}
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.list}
      renderItem={({ item }) => {
        const active = item.id === value;
        return (
          <Pressable
            accessibilityRole="button"
            accessibilityState={{ selected: active }}
            style={[styles.card, active && styles.cardActive]}
            onPress={() => onSelect(item.id)}
          >
            <CaptionPreview style={item} />
            <View style={styles.cardMetaRow}>
              <Text style={styles.cardName} numberOfLines={1}>
                {item.name}
              </Text>
              <ColorSwatches style={item} />
            </View>
            {item.description ? (
              <Text style={styles.cardDesc} numberOfLines={2}>
                {item.description}
              </Text>
            ) : null}
          </Pressable>
        );
      }}
    />
  );
}

const styles = StyleSheet.create({
  center: { paddingVertical: 20, alignItems: "center", gap: 10 },
  list: { gap: 10, paddingVertical: 2, paddingRight: 4 },
  card: {
    width: 180,
    gap: 8,
    backgroundColor: "#0f0f10",
    borderColor: "#27272a",
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
  },
  cardActive: { borderColor: "#E6C76A", borderWidth: 2 },
  preview: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 4,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(0,0,0,0.7)",
    borderRadius: 8,
    paddingVertical: 10,
    paddingHorizontal: 8,
  },
  previewWord: { fontSize: 14, fontWeight: "800" },
  cardMetaRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  cardName: { color: "#ece9e1", fontSize: 14, fontWeight: "600", flexShrink: 1 },
  cardDesc: { color: "#6f6c65", fontSize: 12 },
  swatches: { flexDirection: "row", gap: 6 },
  swatch: {
    width: 16,
    height: 16,
    borderRadius: 8,
    borderColor: "#27272a",
    borderWidth: 1,
  },
  error: { color: "#ff6b6b", fontSize: 14, textAlign: "center" },
  empty: { color: "#6f6c65", fontSize: 13 },
  retry: {
    backgroundColor: "#0f0f10",
    borderColor: "#27272a",
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  retryText: { color: "#ece9e1", fontWeight: "600" },
});
