/**
 * Menivor's tab bar: a floating film-strip rail. Icon-only destinations (each
 * with an accessibility label); the active one sits in a gold "tally light"
 * so you always know which reel deck you are on.
 */
import type { BottomTabBarProps } from "@react-navigation/bottom-tabs";
import { Pressable, StyleSheet, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { palette } from "@/src/shared/theme/tokens";

import { frameDepth } from "./depth";
import { isTabHidden } from "./tab-visibility";

const PERFORATIONS = 9;

export function ReelTabBar({ state, descriptors, navigation }: BottomTabBarProps) {
  const insets = useSafeAreaInsets();

  return (
    <View style={[styles.outer, { paddingBottom: Math.max(insets.bottom, 12) }]}>
      <View style={[styles.rail, { boxShadow: frameDepth }]}>
        <View style={styles.perforations} pointerEvents="none">
          {Array.from({ length: PERFORATIONS }, (_, i) => (
            <View key={i} style={styles.hole} />
          ))}
        </View>
        <View style={styles.row}>
          {state.routes.map((route, index) => {
            const focused = state.index === index;
            const { options } = descriptors[route.key] ?? { options: {} };
            if (isTabHidden(options)) return null;
            const label =
              options.tabBarAccessibilityLabel ??
              (typeof options.title === "string" ? options.title : route.name);
            const color = focused ? palette.accentInk : palette.paperMuted;
            const icon = options.tabBarIcon?.({ focused, color, size: 22 });

            const onPress = () => {
              const event = navigation.emit({ type: "tabPress", target: route.key, canPreventDefault: true });
              if (!focused && !event.defaultPrevented) navigation.navigate(route.name, route.params);
            };

            return (
              <Pressable
                key={route.key}
                onPress={onPress}
                onLongPress={() => navigation.emit({ type: "tabLongPress", target: route.key })}
                accessibilityRole="tab"
                accessibilityState={{ selected: focused }}
                accessibilityLabel={label}
                hitSlop={6}
                style={styles.slot}
              >
                <View style={[styles.tally, focused && styles.tallyOn]}>{icon}</View>
              </Pressable>
            );
          })}
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  outer: { backgroundColor: palette.ink, paddingHorizontal: 18, paddingTop: 6 },
  rail: {
    borderRadius: 22,
    backgroundColor: palette.surface,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: palette.border,
    overflow: "hidden",
  },
  perforations: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingHorizontal: 20,
    paddingTop: 5,
  },
  hole: { width: 8, height: 3, borderRadius: 1.5, backgroundColor: palette.surfaceAlt },
  row: { flexDirection: "row", justifyContent: "space-around", paddingVertical: 8 },
  slot: { flex: 1, alignItems: "center" },
  tally: {
    width: 48,
    height: 38,
    borderRadius: 14,
    alignItems: "center",
    justifyContent: "center",
  },
  tallyOn: { backgroundColor: palette.accent },
});
