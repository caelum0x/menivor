/**
 * NavGroupedList — the default (non-search) hub body: a Pinned shortcut row, a
 * Recent row, then every registry group as a titled section. Each item is a
 * {@link NavRow} carrying its live badge and a pin toggle.
 */

import { StyleSheet, Text, View } from "react-native";

import { Button } from "@/components/ui/Button";
import { colors } from "@/components/me/theme";
import { spacing } from "@/src/shared/theme";
import { badgeForRoute } from "@/lib/nav/badges";
import { getScreen, type ScreenGroup } from "@/lib/nav/registry";
import type { NavHubData } from "@/lib/nav/useNavHubData";
import { NavRow } from "./NavRow";

export interface NavGroupedListProps {
  groups: readonly ScreenGroup[];
  pins: readonly string[];
  recents: readonly string[];
  data: NavHubData;
  onOpen: (route: string) => void;
  onTogglePin: (route: string) => void;
  onClearRecents: () => void;
  /** Open the focused single-group view (deep-links to the [group] screen). */
  onSeeAllGroup?: (group: string) => void;
}

function resolve(routes: readonly string[]) {
  return routes
    .map((route) => getScreen(route))
    .filter((s): s is NonNullable<ReturnType<typeof getScreen>> => !!s && !s.hidden);
}

export function NavGroupedList({
  groups,
  pins,
  recents,
  data,
  onOpen,
  onTogglePin,
  onClearRecents,
  onSeeAllGroup,
}: NavGroupedListProps): React.JSX.Element {
  const pinScreens = resolve(pins);
  const recentScreens = resolve(recents).filter((s) => !pins.includes(s.route));
  const pinSet = new Set(pins);

  return (
    <View style={styles.container}>
      {pinScreens.length > 0 ? (
        <View style={styles.group}>
          <Text style={styles.groupTitle}>Pinned</Text>
          {pinScreens.map((screen) => (
            <NavRow
              key={screen.route}
              screen={screen}
              badge={badgeForRoute(screen.route, data)}
              pinned
              onOpen={onOpen}
              onTogglePin={onTogglePin}
            />
          ))}
        </View>
      ) : null}

      {recentScreens.length > 0 ? (
        <View style={styles.group}>
          <View style={styles.recentHeader}>
            <Text style={styles.groupTitle}>Recent</Text>
            <Button
              label="Clear"
              variant="ghost"
              size="sm"
              onPress={onClearRecents}
            />
          </View>
          {recentScreens.map((screen) => (
            <NavRow
              key={screen.route}
              screen={screen}
              badge={badgeForRoute(screen.route, data)}
              pinned={pinSet.has(screen.route)}
              onOpen={onOpen}
              onTogglePin={onTogglePin}
            />
          ))}
        </View>
      ) : null}

      {groups.map((group) => (
        <View key={group.name} style={styles.group}>
          <View style={styles.recentHeader}>
            <Text style={styles.groupTitle}>{group.name}</Text>
            {onSeeAllGroup && group.screens.length > 0 ? (
              <Button
                label="See all"
                variant="ghost"
                size="sm"
                onPress={() => onSeeAllGroup(group.name)}
              />
            ) : null}
          </View>
          {group.screens.map((screen) => (
            <NavRow
              key={screen.route}
              screen={screen}
              badge={badgeForRoute(screen.route, data)}
              pinned={pinSet.has(screen.route)}
              onOpen={onOpen}
              onTogglePin={onTogglePin}
            />
          ))}
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { gap: spacing.xl },
  group: { gap: spacing.sm },
  recentHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  groupTitle: {
    color: colors.muted,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 1.2,
    textTransform: "uppercase",
    paddingLeft: 2,
  },
});
