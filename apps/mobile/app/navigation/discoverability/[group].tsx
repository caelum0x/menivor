/**
 * Single-group navigation view — a focused, searchable list of every screen in
 * one registry group (e.g. /navigation/discoverability/Monetize). Reachable as
 * a "see all" deep-link and useful as a compact contextual target.
 *
 * NAV MANIFEST:
 *   route: /navigation/discoverability/[group]   (param: group = group name)
 *   parent hub: app/navigation/discoverability/index.tsx
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { useLocalSearchParams, useRouter } from "expo-router";

import { EmptyState } from "@/components/ui/EmptyState";
import { Screen } from "@/components/ui/Screen";
import { SearchBar } from "@/components/ui/SearchBar";
import { colors } from "@/components/me/theme";
import { spacing, typeScale, weight } from "@/src/shared/theme";
import { NavRow } from "@/components/nav/NavRow";
import { badgeForRoute } from "@/lib/nav/badges";
import { getRegistryGroups } from "@/lib/nav/registry";
import { searchScreens } from "@/lib/nav/search";
import { loadPins, pushRecent, togglePin } from "@/lib/nav/recents";
import { useNavHubData } from "@/lib/nav/useNavHubData";
import { usePlatformAdmin } from "@/lib/nav/usePlatformAdmin";
import { useSession } from "@/src/shared/auth";
import { isRouteAvailable } from "@/src/shared/release/surface";

export default function NavigationGroupScreen(): React.JSX.Element {
  const params = useLocalSearchParams<{ group?: string }>();
  const groupName = typeof params.group === "string" ? params.group : "";
  const router = useRouter();
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const hub = useNavHubData(token);
  const [query, setQuery] = useState("");
  const [pins, setPins] = useState<readonly string[]>([]);

  useEffect(() => {
    void loadPins().then(setPins);
  }, []);

  const includeStaff = usePlatformAdmin();
  const group = useMemo(
    () => getRegistryGroups({ includeStaff }).find((g) => g.name === groupName),
    [groupName, includeStaff],
  );

  const screens = useMemo(() => {
    const all = group?.screens ?? [];
    if (query.trim().length === 0) return all;
    return searchScreens(query, all).map((r) => r.screen);
  }, [group, query]);

  const onOpen = useCallback(
    (route: string) => {
      void pushRecent(route);
      router.push(route as Parameters<typeof router.push>[0]);
    },
    [router],
  );

  const onTogglePin = useCallback((route: string) => {
    void togglePin(route).then(setPins);
  }, []);

  const pinSet = new Set(pins);

  return (
    <Screen scroll refreshing={hub.loading} onRefresh={hub.reload}>
      <View style={styles.header}>
        <Text style={styles.title}>{groupName || "Group"}</Text>
        <Text style={styles.subtitle}>
          {group ? `${group.screens.length} screens` : "Unknown group"}
        </Text>
      </View>

      {group ? (
        <SearchBar
          value={query}
          onChangeText={setQuery}
          placeholder={`Search in ${groupName}…`}
          style={styles.search}
        />
      ) : null}

      <View style={styles.body}>
        {!group ? (
          <EmptyState
            title="Group not found"
            body="This navigation group no longer exists."
            actionLabel="Back to hub"
            onAction={() =>
              router.replace(
                isRouteAvailable("/navigation/discoverability") ? "/navigation/discoverability" : "/(tabs)/me",
              )
            }
          />
        ) : screens.length === 0 ? (
          <EmptyState
            title="No screens match"
            body={`Nothing in ${groupName} matches "${query.trim()}".`}
          />
        ) : (
          screens.map((screen) => (
            <NavRow
              key={screen.route}
              screen={screen}
              badge={badgeForRoute(screen.route, hub.data)}
              pinned={pinSet.has(screen.route)}
              onOpen={onOpen}
              onTogglePin={onTogglePin}
            />
          ))
        )}
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  header: { gap: 4, marginBottom: spacing.md },
  title: {
    color: colors.textPrimary,
    fontSize: typeScale.title,
    fontWeight: weight.black,
    textTransform: "capitalize",
  },
  subtitle: { color: colors.textSecondary, fontSize: 13 },
  search: { marginBottom: spacing.md },
  body: { gap: spacing.sm },
});
