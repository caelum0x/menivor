/**
 * Reel-create horizontal row of curated job templates from
 * GET /catalog/templates. Choosing one pre-fills the create form (subject,
 * layout, caption style, language, duration) via `onApply`. Handles loading,
 * error, and empty states. Mirrors web/components/wizard/TemplateGallery.tsx.
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

import { ApiError, listTemplates } from "@/lib/api";
import type { Template } from "@/lib/types";

interface TemplatesRowProps {
  /** Currently-applied template id, or null when starting from scratch. */
  value: string | null;
  /** Called with the chosen template so the form can pre-fill its fields. */
  onApply: (template: Template) => void;
  token?: string;
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; templates: Template[] };

export function TemplatesRow({ value, onApply, token }: TemplatesRowProps) {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  const load = useCallback(async () => {
    setState({ status: "loading" });
    try {
      const templates = await listTemplates({ token });
      setState({ status: "ready", templates });
    } catch (err) {
      setState({
        status: "error",
        message:
          err instanceof ApiError
            ? err.message
            : "Could not load templates. Please try again.",
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

  if (state.templates.length === 0) {
    return <Text style={styles.empty}>No templates are available yet.</Text>;
  }

  return (
    <FlatList
      horizontal
      data={state.templates}
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
            onPress={() => onApply(item)}
          >
            <Text style={styles.cardName} numberOfLines={1}>
              {item.name}
            </Text>
            {item.description ? (
              <Text style={styles.cardDesc} numberOfLines={3}>
                {item.description}
              </Text>
            ) : null}
            <Text style={styles.cardMeta} numberOfLines={1}>
              {String(item.layout)} · {String(item.language)} ·{" "}
              {item.target_duration_s}s
            </Text>
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
    width: 200,
    gap: 6,
    backgroundColor: "#0f0f10",
    borderColor: "#27272a",
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
  },
  cardActive: { borderColor: "#E6C76A", borderWidth: 2 },
  cardName: { color: "#ece9e1", fontSize: 15, fontWeight: "700" },
  cardDesc: { color: "#ece9e1", fontSize: 12, lineHeight: 16 },
  cardMeta: { color: "#6f6c65", fontSize: 11, marginTop: 2 },
  error: { color: "#E0847F", fontSize: 14, textAlign: "center" },
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
