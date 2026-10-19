import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";

import {
  getPopularTemplates,
  getTemplateHistory,
  listTemplates,
  type PopularTemplate,
  type TemplateHistoryEntry,
  type TemplateSummary,
} from "@/lib/templates";
import { ApiError, isAbortError } from "@/lib/api";

interface TemplateBrowserProps {
  token: string | undefined;
  /** Called with the chosen template slug to advance to the input form. */
  onSelect: (slug: string) => void;
}

interface BrowserData {
  templates: TemplateSummary[];
  popular: PopularTemplate[];
  history: TemplateHistoryEntry[];
}

const EMPTY: BrowserData = { templates: [], popular: [], history: [] };

function describe(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Could not load templates.";
}

/**
 * Browse the seeded viral-genre templates. The core `listTemplates` feed is
 * required; the `popular` analytics + personal `history` are best-effort
 * (they 503 when the analytics DB is off) and simply hide when unavailable.
 */
export function TemplateBrowser({ token, onSelect }: TemplateBrowserProps) {
  const [data, setData] = useState<BrowserData>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (signal?: AbortSignal): Promise<void> => {
      setError(null);
      try {
        // The browse feed is required; analytics degrade to empty on failure.
        const [templatesRes, popular, history] = await Promise.all([
          listTemplates({ token, signal }),
          getPopularTemplates({ token, signal }).catch(() => [] as PopularTemplate[]),
          getTemplateHistory({ token, signal }).catch(() => [] as TemplateHistoryEntry[]),
        ]);
        setData({ templates: templatesRes.templates, popular, history });
      } catch (err) {
        if (isAbortError(err)) return;
        setError(describe(err));
      }
    },
    [token],
  );

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setLoading(true);
    void load(controller.signal).finally(() => {
      if (active) setLoading(false);
    });
    return () => {
      active = false;
      controller.abort();
    };
  }, [load]);

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    void load().finally(() => setRefreshing(false));
  }, [load]);

  if (loading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator color="#E6C76A" />
        <Text style={styles.meta}>Loading templates…</Text>
      </View>
    );
  }

  if (error) {
    return (
      <View style={styles.centered}>
        <View style={styles.errorBanner}>
          <Text style={styles.errorText}>{error}</Text>
        </View>
        <Pressable style={styles.retry} onPress={onRefresh}>
          <Text style={styles.retryText}>Try again</Text>
        </Pressable>
      </View>
    );
  }

  const nameBySlug = new Map(data.templates.map((t) => [t.slug, t.name] as const));

  return (
    <FlatList
      style={styles.container}
      contentContainerStyle={styles.content}
      data={data.templates}
      keyExtractor={(t) => t.slug}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={onRefresh}
          tintColor="#E6C76A"
        />
      }
      ListHeaderComponent={
        <View>
          <Text style={styles.intro}>
            Pick a proven viral format — each compiles the hook, pacing, captions
            and audio for you.
          </Text>

          {data.popular.length > 0 ? (
            <View style={styles.section}>
              <Text style={styles.h2}>Popular right now</Text>
              <View style={styles.chips}>
                {data.popular.map((p) => (
                  <Pressable
                    key={p.template_slug}
                    style={styles.chip}
                    onPress={() => onSelect(p.template_slug)}
                  >
                    <Text style={styles.chipText}>
                      {nameBySlug.get(p.template_slug) ?? p.template_slug}
                    </Text>
                    <Text style={styles.chipCount}>{p.count}×</Text>
                  </Pressable>
                ))}
              </View>
            </View>
          ) : null}

          {data.history.length > 0 ? (
            <View style={styles.section}>
              <Text style={styles.h2}>Your recent</Text>
              <View style={styles.chips}>
                {data.history.map((h) => (
                  <Pressable
                    key={h.id}
                    style={styles.chip}
                    onPress={() => onSelect(h.template_slug)}
                  >
                    <Text style={styles.chipText}>
                      {nameBySlug.get(h.template_slug) ?? h.template_slug}
                    </Text>
                    <Text style={styles.chipCount}>{Math.round(h.duration_s)}s</Text>
                  </Pressable>
                ))}
              </View>
            </View>
          ) : null}

          <Text style={styles.h2}>All templates</Text>
        </View>
      }
      renderItem={({ item }) => (
        <Pressable style={styles.card} onPress={() => onSelect(item.slug)}>
          <Text style={styles.name}>{item.name}</Text>
          <Text style={styles.desc}>{item.description}</Text>
          <Text style={styles.metaLine}>
            {item.genre} · {item.aspect} · {item.min_duration_s}–
            {item.max_duration_s}s{item.loopable ? " · loop" : ""}
          </Text>
        </Pressable>
      )}
      ListEmptyComponent={
        <Text style={styles.empty}>
          No templates are available yet. Pull to refresh.
        </Text>
      }
    />
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0a0a0b" },
  content: { padding: 16, paddingBottom: 40 },
  centered: {
    flex: 1,
    backgroundColor: "#0a0a0b",
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
    gap: 12,
  },
  intro: { color: "#ece9e1", fontSize: 14, marginBottom: 8 },
  section: { marginTop: 4 },
  h2: { color: "#ece9e1", fontSize: 16, fontWeight: "700", marginTop: 14, marginBottom: 8 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#0f0f10",
    borderColor: "#27272a",
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  chipText: { color: "#ece9e1", fontWeight: "600" },
  chipCount: { color: "#E6C76A", fontSize: 12, fontWeight: "700" },
  card: {
    backgroundColor: "#0f0f10",
    borderColor: "#27272a",
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 12,
  },
  name: { color: "#ece9e1", fontSize: 16, fontWeight: "600", marginBottom: 4 },
  desc: { color: "#ece9e1", fontSize: 13, marginBottom: 8 },
  metaLine: { color: "#6f6c65", fontSize: 12 },
  meta: { color: "#6f6c65", fontSize: 13 },
  empty: { color: "#6f6c65", fontSize: 14, textAlign: "center", marginTop: 24 },
  errorBanner: {
    backgroundColor: "#2a1420",
    borderColor: "#E0847F",
    borderWidth: 1,
    borderRadius: 10,
    padding: 12,
  },
  errorText: { color: "#E0847F", fontSize: 14 },
  retry: {
    backgroundColor: "#E6C76A",
    borderRadius: 10,
    paddingVertical: 12,
    paddingHorizontal: 20,
  },
  retryText: { color: "#0f0f10", fontWeight: "700" },
});
