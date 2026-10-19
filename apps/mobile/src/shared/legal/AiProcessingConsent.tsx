/**
 * One-time AI processing notice and consent (App Store 5.1.2(i)): before any
 * prompt, link, clip, voice sample or selfie is sent for generation, the
 * creator is told what is sent, where, and why, and explicitly agrees.
 *
 * Acceptance is stored on the device; it is also recorded server-side as a
 * consent entry (best effort) so it shows up in Privacy and data.
 */
import { useCallback, useEffect, useState } from "react";
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Icon, type IconName } from "@/components/ui/Icon";
import { recordConsent } from "@/lib/compliance";
import { palette } from "@/src/shared/theme/tokens";
import { goldPressDepth } from "@/src/ui/menivor/depth";

import { LegalLinks } from "./LegalLinks";

export const AI_CONSENT_KEY = "menivor.ai-processing-consent.v1";

const POINTS: readonly { icon: IconName; text: string }[] = [
  {
    icon: "cloud-upload-outline",
    text: "What you give Menivor to make a video (prompts, links, scripts, clips, images, voice samples and selfies) is sent to Menivor's servers.",
  },
  {
    icon: "sparkles-outline",
    text: "There it is processed by AI service providers that write scripts, generate voices, presenters, b-roll and captions on our behalf.",
  },
  {
    icon: "lock-closed-outline",
    text: "It is used only to make your videos. It is not sold, not used for ads and not used to train AI models.",
  },
  {
    icon: "trash-outline",
    text: "You can delete voices, presenters, uploads or your whole account at any time in Privacy and data.",
  },
];

export interface AiProcessingConsentProps {
  readonly token?: string;
}

export function AiProcessingConsent({ token }: AiProcessingConsentProps) {
  const insets = useSafeAreaInsets();
  const [needed, setNeeded] = useState(false);

  useEffect(() => {
    let active = true;
    AsyncStorage.getItem(AI_CONSENT_KEY)
      .then((value) => {
        if (active) setNeeded(value !== "granted");
      })
      .catch(() => {
        if (active) setNeeded(true);
      });
    return () => {
      active = false;
    };
  }, []);

  const agree = useCallback(async () => {
    setNeeded(false);
    await AsyncStorage.setItem(AI_CONSENT_KEY, "granted").catch(() => undefined);
    await recordConsent("ai_processing", true, { token }).catch(() => undefined);
  }, [token]);

  return (
    <Modal visible={needed} animationType="slide" presentationStyle="pageSheet" onRequestClose={() => undefined}>
      <View style={[styles.root, { paddingBottom: insets.bottom + 16 }]}>
        <ScrollView contentContainerStyle={styles.content}>
          <Text style={styles.kicker}>BEFORE YOUR FIRST REEL</Text>
          <Text style={styles.title} accessibilityRole="header">
            How Menivor makes your video
          </Text>
          {POINTS.map((point) => (
            <View key={point.icon} style={styles.point}>
              <Icon name={point.icon} size={20} color={palette.accent} />
              <Text style={styles.pointText}>{point.text}</Text>
            </View>
          ))}
          <LegalLinks tint={palette.accent} mutedTint={palette.paperFaint} />
        </ScrollView>
        <Pressable
          onPress={() => void agree()}
          style={({ pressed }) => [styles.cta, { boxShadow: goldPressDepth(pressed) }]}
          accessibilityRole="button"
        >
          <Text style={styles.ctaText}>Agree and continue</Text>
        </Pressable>
        <Text style={styles.foot}>
          Menivor cannot make videos without this. You can withdraw by deleting your account.
        </Text>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: palette.ink, paddingHorizontal: 22 },
  content: { paddingTop: 36, paddingBottom: 20, gap: 18 },
  kicker: { color: palette.paperMuted, fontSize: 11, fontWeight: "700", letterSpacing: 2.4 },
  title: { color: palette.paper, fontSize: 28, fontWeight: "800", letterSpacing: -0.8 },
  point: { flexDirection: "row", gap: 14, alignItems: "flex-start" },
  pointText: { color: palette.paper, fontSize: 15, lineHeight: 22, flex: 1 },
  cta: {
    minHeight: 54,
    borderRadius: 16,
    backgroundColor: palette.accent,
    alignItems: "center",
    justifyContent: "center",
  },
  ctaText: { color: palette.accentInk, fontSize: 17, fontWeight: "800" },
  foot: { color: palette.paperFaint, fontSize: 12, lineHeight: 17, textAlign: "center", marginTop: 10 },
});
