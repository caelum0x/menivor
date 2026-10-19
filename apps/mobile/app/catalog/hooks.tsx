/**
 * Hook Lines catalog — browse native opening lines from GET /catalog/hooks,
 * grouped by language code. Switch language, read the lines that stop the scroll
 * in the first 3 seconds, and copy one to reuse in a reel brief.
 *
 * Route: /catalog/hooks
 */

import type { ReactElement } from "react";
import { useCallback, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Clipboard,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { colors } from "@/components/me/theme";
import { useCatalogResource } from "@/components/catalog/use-catalog-resource";
import { useSession } from "@/src/shared/auth";
import { listHooks, type HookCatalog } from "@/lib/catalog";

/** Best-effort English label for a small set of common language codes. */
const LANGUAGE_LABELS: Record<string, string> = {
  en: "English",
  tr: "Türkçe",
  es: "Español",
  de: "Deutsch",
  fr: "Français",
  pt: "Português",
  it: "Italiano",
  ar: "العربية",
  hi: "हिन्दी",
  ja: "日本語",
  ko: "한국어",
  ru: "Русский",
};

function labelFor(code: string): string {
  return LANGUAGE_LABELS[code] ?? code.toUpperCase();
}

export default function HooksCatalogScreen(): ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const [lang, setLang] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  const fetcher = useCallback(() => listHooks({ token }), [token]);
  const { status, data, error, refreshing, reload, refresh } =
    useCatalogResource<HookCatalog>(fetcher);

  const languages = useMemo<string[]>(
    () => (data ? Object.keys(data).filter((k) => (data[k]?.length ?? 0) > 0).sort() : []),
    [data],
  );

  const activeLang = useMemo<string | null>(() => {
    if (lang && languages.includes(lang)) return lang;
    return languages[0] ?? null;
  }, [lang, languages]);

  const lines = useMemo<string[]>(
    () => (data && activeLang ? data[activeLang] ?? [] : []),
    [data, activeLang],
  );

  const onCopy = useCallback((line: string) => {
    Clipboard.setString(line);
    setCopied(line);
    setTimeout(() => setCopied((c) => (c === line ? null : c)), 1500);
  }, []);

  if (status === "loading" && !data) {
    return (
      <View style={[styles.container, styles.center]}>
        <ActivityIndicator color={colors.accent} />
        <Text style={styles.muted}>Loading hook lines…</Text>
      </View>
    );
  }

  if (status === "error" && !data) {
    return (
      <View style={[styles.container, styles.center]}>
        <View style={styles.errorBox}>
          <Text style={styles.errorText}>{error || "Something went wrong."}</Text>
          <Pressable style={styles.retry} onPress={reload} accessibilityRole="button">
            <Text style={styles.retryText}>Try again</Text>
          </Pressable>
        </View>
      </View>
    );
  }

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={refresh}
          tintColor={colors.accent}
          colors={[colors.accent]}
        />
      }
    >
      <Text style={styles.intro}>
        Proven opening lines by language. A strong hook clears the 3-second gate — tap Copy to reuse
        one in your brief.
      </Text>

      {languages.length === 0 ? (
        <View style={styles.emptyBox}>
          <Text style={styles.emptyTitle}>No hook lines</Text>
          <Text style={styles.emptyBody}>
            The hook catalog is currently empty. Pull to refresh to try again.
          </Text>
        </View>
      ) : (
        <>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.tabs}
          >
            {languages.map((code) => {
              const isActive = code === activeLang;
              return (
                <Pressable
                  key={code}
                  style={[styles.tab, isActive && styles.tabActive]}
                  onPress={() => setLang(code)}
                  accessibilityRole="button"
                >
                  <Text style={[styles.tabText, isActive && styles.tabTextActive]}>
                    {labelFor(code)}
                  </Text>
                </Pressable>
              );
            })}
          </ScrollView>

          <Text style={styles.count}>
            {lines.length} {lines.length === 1 ? "line" : "lines"}
          </Text>

          {lines.map((line, index) => (
            <View key={`${activeLang}-${index}`} style={styles.card}>
              <Text style={styles.line}>{line}</Text>
              <Pressable
                style={styles.copyBtn}
                onPress={() => onCopy(line)}
                accessibilityRole="button"
                hitSlop={6}
              >
                <Text style={styles.copyText}>{copied === line ? "Copied" : "Copy"}</Text>
              </Pressable>
            </View>
          ))}
        </>
      )}

      <View style={styles.footer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  center: { alignItems: "center", justifyContent: "center", gap: 10 },
  muted: { color: colors.muted, fontSize: 13 },
  intro: { color: colors.textSecondary, fontSize: 14, marginBottom: 16, lineHeight: 20 },
  tabs: { gap: 8, paddingBottom: 4 },
  tab: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 7,
  },
  tabActive: { backgroundColor: colors.accent, borderColor: colors.accent },
  tabText: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  tabTextActive: { color: colors.bg },
  count: { color: colors.muted, fontSize: 12, marginTop: 12, marginBottom: 8 },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 10,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
  },
  line: { flex: 1, color: colors.textPrimary, fontSize: 15, lineHeight: 21 },
  copyBtn: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 7,
  },
  copyText: { color: colors.textSecondary, fontSize: 12, fontWeight: "700" },
  emptyBox: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 20,
    gap: 6,
  },
  emptyTitle: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  emptyBody: { color: colors.textSecondary, fontSize: 13, lineHeight: 19 },
  errorBox: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 12,
    alignItems: "flex-start",
    alignSelf: "stretch",
  },
  errorText: { color: colors.error, fontSize: 14 },
  retry: { borderColor: colors.border, borderWidth: 1, borderRadius: 8, paddingHorizontal: 14, paddingVertical: 8 },
  retryText: { color: colors.textSecondary, fontWeight: "600" },
  footer: { height: 32 },
});
