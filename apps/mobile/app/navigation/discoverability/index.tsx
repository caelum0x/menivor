/**
 * Navigation hub — a grouped + searchable directory of every deep screen in
 * the app, plus a live activity strip and personal Pinned / Recent shortcuts.
 *
 * This exists because the app's 100+ deep screens were previously only
 * reachable through a single flat registry menu on the Me tab, burying advanced
 * surfaces (Studio, Insights, Wallet, Connections, Workspaces admin, Clip
 * market, Film). The hub restores discoverability: search across all groups,
 * scan by section, and jump to what's live right now (unread alerts, running
 * jobs, wallet credit).
 *
 * NAV MANIFEST (for the nav-integration owner):
 *   route:            /navigation/discoverability
 *   file:             app/navigation/discoverability/index.tsx
 *   self-registers:   yes — group "Navigation", groupOrder 0 (top of Me menu)
 *   child route:      /navigation/discoverability/[group]  (single-group view)
 *   suggested entry:  header/search icon on every tab, or a top row on the Me
 *                     tab. Does NOT modify app/_layout.tsx or the tab layout.
 *   data sources:     GET /me, GET /me/notifications/unread_count, GET /jobs
 *   contextual links: components/nav/ContextualLinks.tsx (wired into the
 *                     Jobs, B-roll funnels; embed elsewhere as needed)
 *
 * Data model: screens live in lib/nav/registry.ts. Adding a screen there makes
 * it appear here automatically — no change to this file needed.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, StyleSheet, Text, View } from "react-native";

import { useRouter } from "expo-router";

import { Screen } from "@/components/ui/Screen";
import { SearchBar } from "@/components/ui/SearchBar";
import { colors } from "@/components/me/theme";
import { spacing, typeScale, weight } from "@/src/shared/theme";
import { NavGroupedList } from "@/components/nav/NavGroupedList";
import { NavSearchResults } from "@/components/nav/NavSearchResults";
import { NavSummary } from "@/components/nav/NavSummary";
import {
  getRegisteredScreens,
  getRegistryGroups,
  registerScreen,
} from "@/lib/nav/registry";
import { searchScreens } from "@/lib/nav/search";
import {
  clearRecents,
  loadPins,
  loadRecents,
  pushRecent,
  togglePin,
} from "@/lib/nav/recents";
import { useNavHubData } from "@/lib/nav/useNavHubData";
import { usePlatformAdmin } from "@/lib/nav/usePlatformAdmin";
import { useSession } from "@/src/shared/auth";

// Self-register so the hub is itself discoverable from the Me tab's menu.
registerScreen({
  route: "/navigation/discoverability",
  title: "Navigation Hub",
  subtitle: "Search and browse every screen, grouped — with live activity",
  group: "Navigation",
  groupOrder: 0,
  order: 1,
  keywords: ["menu", "directory", "find", "all screens", "sitemap", "hub"],
});

export default function NavigationHubScreen(): React.JSX.Element {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();

  const hub = useNavHubData(token);

  const [query, setQuery] = useState("");
  const [pins, setPins] = useState<readonly string[]>([]);
  const [recents, setRecents] = useState<readonly string[]>([]);

  const refreshShortcuts = useCallback(() => {
    void loadPins().then(setPins);
    void loadRecents().then(setRecents);
  }, []);

  useEffect(() => {
    refreshShortcuts();
  }, [refreshShortcuts]);

  const includeStaff = usePlatformAdmin();
  const groups = useMemo(() => getRegistryGroups({ includeStaff }), [includeStaff]);
  const results = useMemo(
    () => searchScreens(query, getRegisteredScreens({ includeStaff })),
    [includeStaff, query],
  );

  const onOpen = useCallback(
    (route: string) => {
      void pushRecent(route).then(setRecents);
      router.push(route as Parameters<typeof router.push>[0]);
    },
    [router],
  );

  const onTogglePin = useCallback((route: string) => {
    void togglePin(route).then(setPins);
  }, []);

  const onSeeAllGroup = useCallback(
    (group: string) => {
      router.push(
        `/navigation/discoverability/${encodeURIComponent(group)}` as Parameters<
          typeof router.push
        >[0],
      );
    },
    [router],
  );

  const onClearRecents = useCallback(() => {
    Alert.alert(
      "Clear recents?",
      "This removes your recently-opened shortcuts on this device.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Clear",
          style: "destructive",
          onPress: () => void clearRecents().then(setRecents),
        },
      ],
    );
  }, []);

  const onRefresh = useCallback(() => {
    hub.reload();
    refreshShortcuts();
  }, [hub, refreshShortcuts]);

  const searching = query.trim().length > 0;

  return (
    <Screen scroll refreshing={hub.loading} onRefresh={onRefresh}>
      <View style={styles.header}>
        <Text style={styles.title}>Explore</Text>
        <Text style={styles.subtitle}>
          Every studio, lab, market and setting — grouped and searchable.
        </Text>
      </View>

      <NavSummary state={hub} onOpen={onOpen} />

      <SearchBar
        value={query}
        onChangeText={setQuery}
        placeholder="Search screens…"
        style={styles.search}
      />

      <View style={styles.body}>
        {searching ? (
          <NavSearchResults
            query={query}
            results={results}
            pins={pins}
            data={hub.data}
            onOpen={onOpen}
            onTogglePin={onTogglePin}
          />
        ) : (
          <NavGroupedList
            groups={groups}
            pins={pins}
            recents={recents}
            data={hub.data}
            onOpen={onOpen}
            onTogglePin={onTogglePin}
            onClearRecents={onClearRecents}
            onSeeAllGroup={onSeeAllGroup}
          />
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
  },
  subtitle: { color: colors.textSecondary, fontSize: 13 },
  search: { marginTop: spacing.md, marginBottom: spacing.md },
  body: { marginTop: spacing.sm },
});
