/**
 * NavSearchResults — the hub body while a search query is active. Renders a
 * flat, relevance-ranked list of matches (each labelled with its group) and an
 * EmptyState when nothing matches.
 */

import { StyleSheet, Text, View } from "react-native";

import { EmptyState } from "@/components/ui/EmptyState";
import { colors } from "@/components/me/theme";
import { spacing } from "@/src/shared/theme";
import { badgeForRoute } from "@/lib/nav/badges";
import type { RankedScreen } from "@/lib/nav/search";
import type { NavHubData } from "@/lib/nav/useNavHubData";
import { NavRow } from "./NavRow";

export interface NavSearchResultsProps {
  query: string;
  results: readonly RankedScreen[];
  pins: readonly string[];
  data: NavHubData;
  onOpen: (route: string) => void;
  onTogglePin: (route: string) => void;
}

export function NavSearchResults({
  query,
  results,
  pins,
  data,
  onOpen,
  onTogglePin,
}: NavSearchResultsProps): React.JSX.Element {
  const pinSet = new Set(pins);

  if (results.length === 0) {
    return (
      <EmptyState
        title="No screens match"
        body={`Nothing found for "${query.trim()}". Try a shorter or different term.`}
      />
    );
  }

  return (
    <View style={styles.container}>
      <Text style={styles.count}>
        {results.length} {results.length === 1 ? "result" : "results"}
      </Text>
      {results.map(({ screen }) => (
        <NavRow
          key={screen.route}
          screen={screen}
          caption={screen.group}
          badge={badgeForRoute(screen.route, data)}
          pinned={pinSet.has(screen.route)}
          onOpen={onOpen}
          onTogglePin={onTogglePin}
        />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { gap: spacing.md },
  count: {
    color: colors.muted,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 1,
    textTransform: "uppercase",
    paddingLeft: 2,
  },
});
