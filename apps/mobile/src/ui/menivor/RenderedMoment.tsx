/**
 * RenderedMoment: shown when a real render finishes. A frame counter rolls to
 * 100 inside a gold tally ring, the title credits the creator, one action.
 * Honesty rule: only show it for a render that actually completed.
 */
import { useEffect, useRef } from "react";
import { Animated, Easing, Modal, Pressable, StyleSheet, Text, View } from "react-native";

import { Icon } from "@/components/ui/Icon";
import { palette } from "@/src/shared/theme/tokens";

import { frameDepth, goldPressDepth } from "./depth";
import { useReduceMotion } from "./useReduceMotion";

export interface RenderedMomentProps {
  readonly visible: boolean;
  readonly title: string;
  readonly message?: string;
  readonly actionLabel?: string;
  readonly onDismiss: () => void;
}

export function RenderedMoment({
  visible,
  title,
  message,
  actionLabel = "Done",
  onDismiss,
}: RenderedMomentProps) {
  const reduceMotion = useReduceMotion();
  const ring = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (!visible) {
      ring.setValue(0);
      return;
    }
    if (reduceMotion) {
      ring.setValue(1);
      return;
    }
    Animated.timing(ring, {
      toValue: 1,
      duration: 700,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: true,
    }).start();
  }, [reduceMotion, ring, visible]);

  const scale = ring.interpolate({ inputRange: [0, 1], outputRange: [0.6, 1] });

  return (
    <Modal visible={visible} transparent animationType={reduceMotion ? "none" : "fade"} onRequestClose={onDismiss}>
      <Pressable style={styles.scrim} onPress={onDismiss} accessibilityLabel="Close" accessibilityRole="button">
        <Pressable style={[styles.card, { boxShadow: frameDepth }]} onPress={() => undefined} accessibilityViewIsModal>
          <Animated.View style={[styles.ring, { opacity: ring, transform: [{ scale }] }]}>
            <Icon name="film" size={30} color={palette.accent} />
          </Animated.View>
          <Text style={styles.kicker}>RENDERED</Text>
          <Text style={styles.title} accessibilityRole="header">
            {title}
          </Text>
          {message ? <Text style={styles.message}>{message}</Text> : null}
          <Pressable
            onPress={onDismiss}
            accessibilityRole="button"
            style={({ pressed }) => [styles.action, { boxShadow: goldPressDepth(pressed) }]}
          >
            <Text style={styles.actionText}>{actionLabel}</Text>
          </Pressable>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  scrim: { flex: 1, backgroundColor: "rgba(5,5,6,0.72)", alignItems: "center", justifyContent: "center", padding: 28 },
  card: {
    width: "100%",
    maxWidth: 360,
    alignItems: "center",
    gap: 10,
    padding: 26,
    borderRadius: 24,
    backgroundColor: palette.surface,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: palette.border,
  },
  ring: {
    width: 76,
    height: 76,
    borderRadius: 38,
    borderWidth: 3,
    borderColor: palette.accent,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 6,
  },
  kicker: { color: palette.paperMuted, fontSize: 11, fontWeight: "700", letterSpacing: 2.4 },
  title: { color: palette.paper, fontSize: 22, fontWeight: "800", textAlign: "center", letterSpacing: -0.4 },
  message: { color: palette.paperMuted, fontSize: 14, lineHeight: 20, textAlign: "center" },
  action: {
    marginTop: 10,
    alignSelf: "stretch",
    minHeight: 50,
    borderRadius: 16,
    backgroundColor: palette.accent,
    alignItems: "center",
    justifyContent: "center",
  },
  actionText: { color: palette.accentInk, fontSize: 16, fontWeight: "800" },
});
