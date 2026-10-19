/**
 * Dub Languages catalog — browse the target languages a finished reel can be
 * dubbed into (GET /dub/languages). Multi-select the languages you want (dubbing
 * fans out to N languages at once), see the running credit cost, and save the
 * set for your next reel (persisted locally as `dub_languages`).
 *
 * Route: /catalog/dub-languages
 */

import type { ReactElement } from "react";
import { useCallback, useMemo } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors } from "@/components/me/theme";
import { CatalogList } from "@/components/catalog/CatalogList";
import { useCatalogResource } from "@/components/catalog/use-catalog-resource";
import { useSession } from "@/src/shared/auth";
import { listDubLanguages, useCatalogSelection, type DubLanguage } from "@/lib/catalog";

const DEFAULT_CREDIT_COST = 1;

function costOf(lang: DubLanguage): number {
  const c = lang.credit_cost;
  return typeof c === "number" && Number.isFinite(c) && c > 0 ? c : DEFAULT_CREDIT_COST;
}

export default function DubLanguagesScreen(): ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const { selection, toggleDub } = useCatalogSelection();

  const fetcher = useCallback(() => listDubLanguages({ token }), [token]);
  const { status, data, error, refreshing, reload, refresh } =
    useCatalogResource<DubLanguage[]>(fetcher);

  const items = useMemo<DubLanguage[]>(() => data ?? [], [data]);
  const selectedCodes = useMemo<ReadonlySet<string>>(
    () => new Set(selection.dubLanguages ?? []),
    [selection.dubLanguages],
  );

  const totalCredits = useMemo<number>(
    () =>
      items
        .filter((l) => selectedCodes.has(String(l.code)))
        .reduce((sum, l) => sum + costOf(l), 0),
    [items, selectedCodes],
  );

  const onToggle = useCallback(
    async (lang: DubLanguage) => {
      await toggleDub(String(lang.code));
    },
    [toggleDub],
  );

  const renderItem = useCallback(
    (lang: DubLanguage): ReactElement => {
      const code = String(lang.code);
      const isSelected = selectedCodes.has(code);
      const cost = costOf(lang);
      return (
        <Pressable
          style={[styles.card, isSelected && styles.cardSelected]}
          onPress={() => void onToggle(lang)}
          accessibilityRole="checkbox"
          accessibilityState={{ checked: isSelected }}
        >
          <View style={[styles.checkbox, isSelected && styles.checkboxOn]}>
            {isSelected ? <View style={styles.checkboxDot} /> : null}
          </View>
          <View style={styles.info}>
            <Text style={styles.name}>
              {lang.name}
              {lang.native_name && lang.native_name !== lang.name ? (
                <Text style={styles.native}> · {lang.native_name}</Text>
              ) : null}
            </Text>
            <Text style={styles.meta}>
              {code} · {cost} {cost === 1 ? "credit" : "credits"}
            </Text>
          </View>
        </Pressable>
      );
    },
    [onToggle, selectedCodes],
  );

  const selectedCount = selectedCodes.size;
  const header = (
    <View style={styles.summary}>
      <Text style={styles.summaryTitle}>
        {selectedCount === 0
          ? "No languages selected"
          : `${selectedCount} ${selectedCount === 1 ? "language" : "languages"} selected`}
      </Text>
      <Text style={styles.summaryCost}>
        {totalCredits} {totalCredits === 1 ? "credit" : "credits"} to dub
      </Text>
    </View>
  );

  return (
    <CatalogList<DubLanguage>
      status={status}
      error={error}
      items={items}
      keyExtractor={(l) => String(l.code)}
      renderItem={renderItem}
      onRetry={reload}
      refreshing={refreshing}
      onRefresh={refresh}
      intro="Dub a finished reel into these languages — each keeps the same footage, voice and captions. Select every language you want; the credit cost adds up."
      header={header}
      emptyTitle="No dub languages"
      emptyBody="The dubbing catalog returned nothing. Pull to refresh to try again."
      loadingLabel="Loading languages…"
    />
  );
}

const styles = StyleSheet.create({
  summary: {
    backgroundColor: colors.card,
    borderColor: colors.accent,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 14,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  summaryTitle: { color: colors.textPrimary, fontSize: 14, fontWeight: "700" },
  summaryCost: { color: colors.accent, fontSize: 14, fontWeight: "700" },
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
  cardSelected: { borderColor: colors.accent },
  checkbox: {
    width: 22,
    height: 22,
    borderRadius: 6,
    borderColor: colors.border,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  checkboxOn: { backgroundColor: colors.accent, borderColor: colors.accent },
  checkboxDot: { width: 10, height: 10, borderRadius: 2, backgroundColor: colors.bg },
  info: { flex: 1, gap: 3 },
  name: { color: colors.textPrimary, fontSize: 15, fontWeight: "600" },
  native: { color: colors.textSecondary, fontSize: 14, fontWeight: "400" },
  meta: { color: colors.muted, fontSize: 12 },
});
