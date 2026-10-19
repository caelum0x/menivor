/**
 * Catalog hub — the entry point into the content-catalog browsers.
 *
 * Surfaces every `GET /catalog/*` gallery (caption styles, music, layouts,
 * templates, hooks, cover styles, dub languages) as a browsable menu, and shows
 * the creator's current compose picks (persisted device-locally) so they can
 * see and clear what they've chosen before composing a reel.
 *
 * NAV MANIFEST (routes for the integration agent to wire into navigation):
 *   { route: "/catalog",                 title: "Catalog" }
 *   { route: "/catalog/model-catalog",   title: "Model Catalog" }
 *   { route: "/catalog/model/[id]",      title: "Model" }
 *   { route: "/catalog/provider-health", title: "Provider Health" }
 *   { route: "/catalog/quote",           title: "Estimate Cost" }
 *   { route: "/catalog/presets",         title: "Motion & VFX" }
 *   { route: "/catalog/caption-styles",  title: "Caption Styles" }
 *   { route: "/catalog/music",           title: "Music Library" }
 *   { route: "/catalog/layouts",         title: "Layouts" }
 *   { route: "/catalog/backgrounds",     title: "Backgrounds" }
 *   { route: "/catalog/templates",       title: "Templates" }
 *   { route: "/catalog/hooks",           title: "Hook Lines" }
 *   { route: "/catalog/cover-styles",    title: "Cover Styles" }
 *   { route: "/catalog/dub-languages",   title: "Dub Languages" }
 *   { route: "/catalog/reddit-story",    title: "Reddit Story" }
 *   { route: "/catalog/trend-pull",      title: "Pull Trends" }
 *   { route: "/catalog/studio",          title: "Stock Libraries" }
 */

import type { ReactElement } from "react";
import { Alert, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { Link, useFocusEffect } from "expo-router";
import { useCallback } from "react";

import { colors } from "@/components/me/theme";
import { useCatalogSelection } from "@/lib/catalog";

interface CatalogEntry {
  route: string;
  title: string;
  kicker: string;
  description: string;
}

const ENTRIES: readonly CatalogEntry[] = [
  {
    route: "/catalog/reddit-story",
    title: "Reddit Story",
    kicker: "00 / INGEST",
    description: "Turn a Reddit thread URL into a narrated split-screen story reel draft.",
  },
  {
    route: "/catalog/trend-pull",
    title: "Pull Trends",
    kicker: "00 / INGEST",
    description: "Scrape a hashtag, sound or the For-You feed on demand to seed fresh, scored trends.",
  },
  {
    route: "/catalog/model-catalog",
    title: "Model Catalog",
    kicker: "00 / MODELS",
    description: "Compare reviewed models live by price and provider health, then estimate cost.",
  },
  {
    route: "/catalog/provider-health",
    title: "Provider Health",
    kicker: "00 / STATUS",
    description: "Live uptime, latency and state for every generation provider.",
  },
  {
    route: "/catalog/quote",
    title: "Estimate Cost",
    kicker: "00 / QUOTE",
    description: "Price your model choices before you render — a signed pay-as-you-go quote.",
  },
  {
    route: "/catalog/presets",
    title: "Motion & VFX",
    kicker: "00 / EFFECTS",
    description: "One-click camera moves and stackable cinematic VFX the pipeline can apply.",
  },
  {
    route: "/catalog/caption-styles",
    title: "Caption Styles",
    kicker: "01 / CAPTIONS",
    description: "Burned-in subtitle presets — colour, weight and highlight for spoken words.",
  },
  {
    route: "/catalog/music",
    title: "Music Library",
    kicker: "02 / SOUND",
    description: "Licensed background tracks you can drop under a reel.",
  },
  {
    route: "/catalog/layouts",
    title: "Layouts",
    kicker: "03 / FRAME",
    description: "Composition templates — picture-in-picture, split screen, full frame.",
  },
  {
    route: "/catalog/backgrounds",
    title: "Backgrounds",
    kicker: "03 / FRAME",
    description: "Loop-able footage behind split-screen and loop reels — gameplay, ASMR, driving.",
  },
  {
    route: "/catalog/templates",
    title: "Templates",
    kicker: "04 / START",
    description: "Curated starting points that pre-fill a whole reel brief.",
  },
  {
    route: "/catalog/hooks",
    title: "Hook Lines",
    kicker: "05 / OPEN",
    description: "Native opening lines by language to stop the scroll in the first 3s.",
  },
  {
    route: "/catalog/cover-styles",
    title: "Cover Styles",
    kicker: "06 / THUMB",
    description: "Headline treatments for the scroll-stopping cover image.",
  },
  {
    route: "/catalog/dub-languages",
    title: "Dub Languages",
    kicker: "07 / REACH",
    description: "Target languages a finished reel can be dubbed into.",
  },
  {
    route: "/catalog/studio",
    title: "Stock Libraries",
    kicker: "08 / ASSETS",
    description:
      "Uploadable stores of background music and local footage the pipeline pulls from.",
  },
] as const;

function SelectionSummary(): ReactElement | null {
  const { selection, ready, clear, reload } = useCatalogSelection();

  useFocusEffect(
    useCallback(() => {
      void reload();
    }, [reload]),
  );

  if (!ready) return null;

  const chips: string[] = [];
  if (selection.captionStyle) chips.push(`Caption · ${selection.captionStyle}`);
  if (selection.musicId) chips.push(`Music · ${selection.musicId}`);
  if (selection.layout) chips.push(`Layout · ${selection.layout}`);
  if (selection.backgroundId) chips.push(`Background · ${selection.backgroundId}`);
  if (selection.templateId) chips.push(`Template · ${selection.templateId}`);
  if (selection.coverStyle) chips.push(`Cover · ${selection.coverStyle}`);
  if (selection.dubLanguages && selection.dubLanguages.length > 0) {
    chips.push(`Dub · ${selection.dubLanguages.length} lang`);
  }

  if (chips.length === 0) return null;

  const onClear = (): void => {
    Alert.alert("Clear picks", "Remove all your saved catalog picks?", [
      { text: "Cancel", style: "cancel" },
      { text: "Clear", style: "destructive", onPress: () => void clear() },
    ]);
  };

  return (
    <View style={styles.summary}>
      <View style={styles.summaryHeader}>
        <Text style={styles.summaryTitle}>Your picks for the next reel</Text>
        <Pressable onPress={onClear} accessibilityRole="button" hitSlop={8}>
          <Text style={styles.clearText}>Clear</Text>
        </Pressable>
      </View>
      <View style={styles.chipRow}>
        {chips.map((chip) => (
          <View key={chip} style={styles.chip}>
            <Text style={styles.chipText}>{chip}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}

export default function CatalogHubScreen(): ReactElement {
  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.intro}>
        Browse the building blocks the pipeline uses to compose a reel. Preview each one, then pick
        it — your choices are saved and applied when you compose.
      </Text>

      <SelectionSummary />

      {ENTRIES.map((entry) => (
        <Link key={entry.route} href={entry.route as never} asChild>
          <Pressable style={styles.card} accessibilityRole="button">
            <Text style={styles.kicker}>{entry.kicker}</Text>
            <Text style={styles.cardTitle}>{entry.title}</Text>
            <Text style={styles.cardDesc}>{entry.description}</Text>
          </Pressable>
        </Link>
      ))}

      <View style={styles.footer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  intro: { color: colors.textSecondary, fontSize: 14, marginBottom: 16, lineHeight: 20 },
  summary: {
    backgroundColor: colors.card,
    borderColor: colors.accent,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 16,
    gap: 10,
  },
  summaryHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  summaryTitle: { color: colors.textPrimary, fontSize: 14, fontWeight: "700" },
  clearText: { color: colors.accent, fontSize: 13, fontWeight: "600" },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    backgroundColor: colors.cardAlt,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 5,
  },
  chipText: { color: colors.textSecondary, fontSize: 12, fontWeight: "500" },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
    gap: 4,
  },
  kicker: {
    color: colors.muted,
    fontSize: 11,
    fontWeight: "600",
    letterSpacing: 1.5,
    marginBottom: 2,
  },
  cardTitle: { color: colors.textPrimary, fontSize: 17, fontWeight: "700" },
  cardDesc: { color: colors.textSecondary, fontSize: 13, lineHeight: 19 },
  footer: { height: 32 },
});
