/**
 * Capture hub — the on-ramp for getting footage into ReelForge. Import a screen
 * recording / clip, or trim & export a completed reel. (Live camera capture is a
 * later add — requires expo-camera.)
 */

import * as React from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { router } from "expo-router";

import { colors } from "@/components/me/theme";
import { Icon } from "@/components/ui/Icon";

const ENTRIES: { href: string; title: string; subtitle: string }[] = [
  {
    href: "/capture/screen-import",
    title: "Import footage",
    subtitle: "Upload a screen recording or clip to use in a template",
  },
  {
    href: "/capture/trim",
    title: "Trim & export",
    subtitle: "Preview a reel, set in/out + speed, export the cut",
  },
  {
    href: "/studio/templates",
    title: "Start from a template",
    subtitle: "One-tap viral formats — footage is auto-filled if you have none",
  },
];

export default function CaptureHub() {
  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.intro}>
        Bring footage in, cut it, or start straight from a template.
      </Text>
      {ENTRIES.map((e) => (
        <Pressable key={e.href} style={styles.link} onPress={() => router.push(e.href as never)}>
          <View style={styles.body}>
            <Text style={styles.title}>{e.title}</Text>
            <Text style={styles.subtitle}>{e.subtitle}</Text>
          </View>
          <Icon name="chevron-forward" style={styles.chevron} />
        </Pressable>
      ))}
      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  intro: { color: colors.textSecondary, fontSize: 14, marginBottom: 16 },
  link: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    backgroundColor: colors.card, borderColor: colors.border, borderWidth: 1,
    borderRadius: 12, padding: 14, marginBottom: 10,
  },
  body: { flex: 1, paddingRight: 8 },
  title: { color: colors.textPrimary, fontSize: 15, fontWeight: "600" },
  subtitle: { color: colors.muted, fontSize: 12, marginTop: 2 },
  chevron: { color: colors.muted, fontSize: 22 },
  spacer: { height: 24 },
});
