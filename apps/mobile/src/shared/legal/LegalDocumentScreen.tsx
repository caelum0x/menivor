/**
 * Renders a bundled legal document (Terms / Privacy). Reachable without a
 * session so it works from the sign-in screen and every paywall surface.
 */

import { Linking, ScrollView, StyleSheet, Text, View } from "react-native";

import { Stack } from "expo-router";

import { colors, spacing, typeScale } from "@/src/shared/theme";

import { LEGAL_CONTACT_EMAIL, type LegalDocument } from "./documents";

export interface LegalDocumentScreenProps {
  readonly document: LegalDocument;
}

export function LegalDocumentScreen({
  document,
}: Readonly<LegalDocumentScreenProps>) {
  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Stack.Screen options={{ title: document.title }} />
      <Text style={styles.title}>{document.title}</Text>
      <Text style={styles.updated}>Last updated {document.updated}</Text>
      <Text style={styles.body}>{document.intro}</Text>
      {document.sections.map((section) => (
        <View key={section.heading} style={styles.section}>
          <Text style={styles.heading}>{section.heading}</Text>
          {section.paragraphs.map((paragraph) => (
            <Text key={paragraph} style={styles.body}>
              {paragraph}
            </Text>
          ))}
        </View>
      ))}
      <Text
        style={styles.link}
        accessibilityRole="link"
        onPress={() =>
          void Linking.openURL(`mailto:${LEGAL_CONTACT_EMAIL}`).catch(
            () => undefined,
          )
        }
      >
        {LEGAL_CONTACT_EMAIL}
      </Text>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.xl, gap: spacing.md, paddingBottom: 48 },
  title: {
    color: colors.textPrimary,
    fontSize: typeScale.title,
    fontWeight: "800",
  },
  updated: { color: colors.textFaint, fontSize: typeScale.caption },
  section: { gap: spacing.sm, marginTop: spacing.sm },
  heading: {
    color: colors.textPrimary,
    fontSize: typeScale.subheading,
    fontWeight: "700",
  },
  body: {
    color: colors.textSecondary,
    fontSize: typeScale.body,
    lineHeight: 22,
  },
  link: {
    color: colors.accent,
    fontSize: typeScale.body,
    fontWeight: "700",
    textDecorationLine: "underline",
    marginTop: spacing.md,
  },
});
