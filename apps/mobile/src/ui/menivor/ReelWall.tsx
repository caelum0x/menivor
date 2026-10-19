/**
 * ReelWall: three columns of code-drawn niche reels drifting past each other,
 * the moving backdrop of the sign-in screen. Every tile is a different niche
 * (no repeated self-ads, no stock photos). Reduce Motion freezes the wall.
 */
import { useEffect, useMemo, useRef } from "react";
import { Animated, Easing, StyleSheet, View, useWindowDimensions } from "react-native";

import { LinearGradient } from "expo-linear-gradient";

import { palette } from "@/src/shared/theme/tokens";

import { NICHE_SCENES } from "./niches";
import { ReelArt } from "./ReelArt";
import { useReduceMotion } from "./useReduceMotion";

const GAP = 8;
const COLUMNS = 3;
const TILES_PER_COLUMN = 4;
/** Seconds for one full loop per column; different speeds read as depth. */
const COLUMN_SECONDS = [46, 38, 52] as const;

function Column({ index, width, moving }: { index: number; width: number; moving: boolean }) {
  const tileHeight = Math.round((width * 16) / 9);
  const loopHeight = TILES_PER_COLUMN * (tileHeight + GAP);
  const offset = useRef(new Animated.Value(0)).current;
  const upward = index % 2 === 0;

  const niches = useMemo(
    () =>
      Array.from({ length: TILES_PER_COLUMN }, (_, row) => {
        const scene = NICHE_SCENES[(index * 3 + row) % NICHE_SCENES.length];
        return scene?.niche ?? "Travel";
      }),
    [index],
  );

  useEffect(() => {
    if (!moving) {
      offset.setValue(0.35);
      return undefined;
    }
    offset.setValue(0);
    const loop = Animated.loop(
      Animated.timing(offset, {
        toValue: 1,
        duration: (COLUMN_SECONDS[index] ?? 44) * 1000,
        easing: Easing.linear,
        useNativeDriver: true,
      }),
    );
    loop.start();
    return () => loop.stop();
  }, [index, moving, offset]);

  const translateY = offset.interpolate({
    inputRange: [0, 1],
    outputRange: upward ? [0, -loopHeight] : [-loopHeight, 0],
  });

  return (
    <Animated.View style={{ width, gap: GAP, transform: [{ translateY }] }}>
      {[...niches, ...niches].map((niche, row) => (
        <ReelArt
          key={`${niche}-${row}`}
          seed={`${index}-${row}`}
          niche={niche}
          moving={moving}
          style={{ width, height: tileHeight, borderRadius: 14 }}
        />
      ))}
    </Animated.View>
  );
}

export function ReelWall() {
  const { width } = useWindowDimensions();
  const reduceMotion = useReduceMotion();
  const columnWidth = Math.floor((width - GAP * (COLUMNS + 1)) / COLUMNS);

  return (
    <View
      style={styles.wall}
      pointerEvents="none"
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
    >
      <View style={[styles.columns, { transform: [{ rotate: "-6deg" }, { scale: 1.12 }] }]}>
        {Array.from({ length: COLUMNS }, (_, index) => (
          <Column key={index} index={index} width={columnWidth} moving={!reduceMotion} />
        ))}
      </View>
      <LinearGradient
        colors={["rgba(10,10,11,0.15)", "rgba(10,10,11,0.55)", palette.ink]}
        locations={[0, 0.45, 0.78]}
        style={StyleSheet.absoluteFill}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  wall: { ...StyleSheet.absoluteFillObject, overflow: "hidden", backgroundColor: palette.ink },
  columns: { flexDirection: "row", gap: GAP, paddingHorizontal: GAP, marginTop: -40 },
});
