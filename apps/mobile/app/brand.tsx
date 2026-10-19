/**
 * Brand Watermark screen. Lets a creator upload a transparent PNG logo and
 * choose the corner + opacity it is overlaid at on their reels, and toggle the
 * watermark on/off. Reached from the Me tab. Auth token comes from the session
 * and is sent as `x-api-key` by the shared api client.
 */

import { ScrollView, StyleSheet, Text, View } from "react-native";

import { BrandManager } from "@/components/brand/BrandManager";
import { colors } from "@/components/me/theme";
import { useSession } from "@/src/shared/auth";

export default function BrandScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
    >
      <Text style={styles.intro}>
        Overlay your logo on every reel. Upload a transparent PNG, choose a
        corner and opacity, and we’ll apply it automatically in the compose
        stage. Individual jobs can still override or disable it.
      </Text>
      <BrandManager token={token} />
      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20, paddingTop: 20 },
  intro: {
    color: colors.textSecondary,
    fontSize: 14,
    lineHeight: 20,
    marginBottom: 20,
  },
  spacer: { height: 40 },
});
