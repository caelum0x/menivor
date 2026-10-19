/**
 * ContextualLinks — a compact deep-link card a funnel screen drops in to expose
 * the advanced surfaces most relevant from where the user is. Data comes from
 * lib/nav/contextual.ts, so the links stay in sync with the registry and never
 * point at an unregistered/hidden screen.
 *
 * Usage (inside a funnel screen):
 * ```tsx
 * import { ContextualLinks } from "@/components/nav/ContextualLinks";
 * <ContextualLinks context="jobs" title="Do more with this reel" />
 * ```
 *
 * Renders nothing when the context resolves to no links, so it is always safe
 * to mount unconditionally.
 */

import { useRouter } from "expo-router";
import { StyleSheet, Text, View } from "react-native";

import { ListRow } from "@/components/ui/ListRow";
import { colors } from "@/components/me/theme";
import { spacing } from "@/src/shared/theme";
import { getContextualLinks, type NavContext } from "@/lib/nav/contextual";
import { pushRecent } from "@/lib/nav/recents";

export interface ContextualLinksProps {
  context: NavContext;
  /** Section heading. Defaults to a neutral prompt. */
  title?: string;
  /** How many links to show (default all for the context). */
  limit?: number;
}

export function ContextualLinks({
  context,
  title = "Go deeper",
  limit,
}: ContextualLinksProps): React.JSX.Element | null {
  const router = useRouter();
  const all = getContextualLinks(context);
  const links = typeof limit === "number" ? all.slice(0, limit) : all;

  if (links.length === 0) return null;

  const open = (route: string): void => {
    void pushRecent(route);
    router.push(route as Parameters<typeof router.push>[0]);
  };

  return (
    <View style={styles.container}>
      <Text style={styles.title}>{title}</Text>
      {links.map((screen) => (
        <ListRow
          key={screen.route}
          title={screen.title}
          subtitle={screen.subtitle}
          onPress={() => open(screen.route)}
          showChevron
          style={styles.row}
        />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { gap: spacing.sm, marginVertical: spacing.md },
  title: {
    color: colors.muted,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 1.2,
    textTransform: "uppercase",
    paddingLeft: 2,
  },
  row: { marginBottom: 0 },
});
