/**
 * ReelArt: a code-drawn vertical reel frame for a niche (gradient light, a
 * subject shape, and a caption line with one gold word). Used for posters that
 * have no rendered frame yet and for the moving reel wall on sign-in.
 */
import { useEffect, useRef } from "react";
import { Animated, Easing, StyleSheet, Text, View, type StyleProp, type ViewStyle } from "react-native";

import { LinearGradient } from "expo-linear-gradient";

import { palette } from "@/src/shared/theme/tokens";

import { sceneFor, type NicheScene } from "./niches";

export interface ReelArtProps {
  /** Stable seed (job id, title) choosing the scene when `niche` is unknown. */
  readonly seed: string;
  readonly niche?: string;
  /** Show the niche label and caption line (off for tiny thumbnails). */
  readonly showText?: boolean;
  /** Slow drift of the subject shape. Pass false for Reduce Motion. */
  readonly moving?: boolean;
  readonly style?: StyleProp<ViewStyle>;
  readonly accessibilityLabel?: string;
}

function Subject({ scene }: { scene: NicheScene }) {
  const [, mid, low] = scene.light;
  switch (scene.shape) {
    case "sun":
      return <View style={[styles.sun, { backgroundColor: low }]} />;
    case "steam":
      return (
        <View style={styles.steamWrap}>
          {[0, 1, 2].map((i) => (
            <View key={i} style={[styles.steam, { borderColor: low, marginLeft: i * 10 }]} />
          ))}
          <View style={[styles.bowl, { backgroundColor: mid, borderColor: low }]} />
        </View>
      );
    case "pulse":
      return (
        <View style={styles.pulseRow}>
          {[18, 34, 56, 30, 70, 40, 22].map((h, i) => (
            <View key={i} style={[styles.pulseBar, { height: h, backgroundColor: low }]} />
          ))}
        </View>
      );
    case "window":
      return (
        <View style={[styles.window, { borderColor: low }]}>
          <View style={[styles.windowBar, { backgroundColor: low }]} />
          <View style={[styles.windowBarV, { backgroundColor: low }]} />
        </View>
      );
    case "grid":
      return (
        <View style={[styles.phone, { borderColor: low }]}>
          {[0, 1, 2].map((i) => (
            <View key={i} style={[styles.phoneRow, { backgroundColor: i === 1 ? palette.accent : low }]} />
          ))}
        </View>
      );
    case "wave":
    default:
      return (
        <View style={styles.waveWrap}>
          {[0, 1, 2].map((i) => (
            <View key={i} style={[styles.wave, { borderColor: low, width: 80 + i * 26, height: 80 + i * 26 }]} />
          ))}
        </View>
      );
  }
}

export function ReelArt({
  seed,
  niche,
  showText = true,
  moving = false,
  style,
  accessibilityLabel,
}: ReelArtProps) {
  const scene = sceneFor(seed, niche);
  const drift = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (!moving) {
      drift.setValue(0);
      return undefined;
    }
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(drift, { toValue: 1, duration: 4200, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
        Animated.timing(drift, { toValue: 0, duration: 4200, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [drift, moving]);

  const translateY = drift.interpolate({ inputRange: [0, 1], outputRange: [0, -10] });
  const scale = drift.interpolate({ inputRange: [0, 1], outputRange: [1, 1.04] });
  const words = scene.caption.split(" ");

  return (
    <View
      style={[styles.frame, style]}
      accessible={Boolean(accessibilityLabel)}
      accessibilityLabel={accessibilityLabel}
    >
      <LinearGradient colors={scene.light as unknown as [string, string, string]} style={StyleSheet.absoluteFill} />
      <Animated.View style={[styles.subject, { transform: [{ translateY }, { scale }] }]}>
        <Subject scene={scene} />
      </Animated.View>
      <LinearGradient
        colors={["rgba(10,10,11,0)", "rgba(10,10,11,0.72)"]}
        style={styles.shade}
      />
      {showText ? (
        <>
          <Text style={styles.niche} numberOfLines={1}>
            {scene.niche.toUpperCase()}
          </Text>
          <Text style={styles.caption} numberOfLines={2}>
            {words.map((word, index) => (
              <Text key={`${word}-${index}`} style={index === scene.highlight ? styles.captionHot : undefined}>
                {index > 0 ? " " : ""}
                {word}
              </Text>
            ))}
          </Text>
        </>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  frame: { overflow: "hidden", backgroundColor: palette.surface },
  subject: { ...StyleSheet.absoluteFillObject, alignItems: "center", justifyContent: "center", paddingBottom: "18%" },
  shade: { position: "absolute", left: 0, right: 0, bottom: 0, height: "55%" },
  niche: {
    position: "absolute",
    top: 10,
    left: 10,
    color: "rgba(236,233,225,0.82)",
    fontSize: 9,
    fontWeight: "700",
    letterSpacing: 1.6,
  },
  caption: {
    position: "absolute",
    left: 10,
    right: 10,
    bottom: 12,
    color: palette.paper,
    fontSize: 13,
    fontWeight: "800",
    lineHeight: 16,
    letterSpacing: -0.2,
  },
  captionHot: { color: palette.accent },
  sun: { width: 70, height: 70, borderRadius: 35, opacity: 0.9 },
  steamWrap: { alignItems: "center" },
  steam: { width: 16, height: 26, borderLeftWidth: 2, borderRadius: 12, opacity: 0.6, marginBottom: -6 },
  bowl: { width: 86, height: 34, borderBottomLeftRadius: 43, borderBottomRightRadius: 43, borderWidth: 2, marginTop: 12 },
  pulseRow: { flexDirection: "row", alignItems: "flex-end", gap: 6 },
  pulseBar: { width: 7, borderRadius: 4, opacity: 0.85 },
  window: { width: 76, height: 96, borderWidth: 2, borderRadius: 4, alignItems: "center", justifyContent: "center", opacity: 0.85 },
  windowBar: { position: "absolute", left: 0, right: 0, height: 2 },
  windowBarV: { position: "absolute", top: 0, bottom: 0, width: 2 },
  phone: { width: 58, height: 104, borderWidth: 2, borderRadius: 12, padding: 8, gap: 8, justifyContent: "center", opacity: 0.9 },
  phoneRow: { height: 10, borderRadius: 3, opacity: 0.9 },
  waveWrap: { alignItems: "center", justifyContent: "center" },
  wave: { position: "absolute", borderWidth: 1.5, borderRadius: 999, opacity: 0.55 },
});
