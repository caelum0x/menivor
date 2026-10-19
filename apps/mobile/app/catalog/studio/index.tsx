/**
 * Stock Libraries hub — entry point into the legacy MoneyPrinterTurbo standalone
 * asset stores that sit alongside the curated `GET /catalog/*` galleries.
 *
 * These two libraries expose the raw server-side file stores the render pipeline
 * pulls from, and (unlike the read-only catalog galleries) they accept uploads:
 *   - Music Library  — GET/POST /musics
 *   - Video Materials — GET/POST /video_materials
 *
 * NAV MANIFEST (routes for the integration agent to wire into navigation):
 *   { route: "/catalog/studio",                   title: "Stock Libraries" }
 *   { route: "/catalog/studio/stock-music",       title: "Music Library (Stock)" }
 *   { route: "/catalog/studio/stock-materials",   title: "Video Materials (Stock)" }
 */

import type { ReactElement } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { Link } from "expo-router";

import { colors } from "@/components/me/theme";

interface StudioEntry {
  route: string;
  title: string;
  kicker: string;
  description: string;
}

const ENTRIES: readonly StudioEntry[] = [
  {
    route: "/catalog/studio/stock-music",
    title: "Music Library",
    kicker: "STOCK / SOUND",
    description:
      "The raw background-music store. Browse every uploaded track or add your own MP3/WAV to use under a reel.",
  },
  {
    route: "/catalog/studio/stock-materials",
    title: "Video Materials",
    kicker: "STOCK / FOOTAGE",
    description:
      "The local clips and stills the pipeline can splice in. Browse the store or upload your own MP4/MOV/JPG.",
  },
] as const;

export default function StockLibrariesHubScreen(): ReactElement {
  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.intro}>
        Uploadable asset stores that feed the render pipeline. Unlike the curated
        catalog galleries, these hold the raw files a job pulls from — and you can
        add your own.
      </Text>

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
  intro: {
    color: colors.textSecondary,
    fontSize: 14,
    marginBottom: 16,
    lineHeight: 20,
  },
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
