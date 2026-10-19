/**
 * RegistryMenu — renders a grouped navigation list driven by the nav registry.
 *
 * Drop this into any screen to get a complete, grouped list of registered
 * screens without hardcoding routes. Adding a new screen to the registry
 * automatically surfaces it here.
 *
 * Usage:
 * ```tsx
 * import { RegistryMenu } from "@/lib/nav/RegistryMenu";
 *
 * export default function HubScreen() {
 *   return (
 *     <ScrollView>
 *       <RegistryMenu />
 *     </ScrollView>
 *   );
 * }
 * ```
 *
 * To show only specific groups:
 * ```tsx
 * <RegistryMenu groups={["Core", "Analytics"]} />
 * ```
 */

import { useRouter } from "expo-router";
import {
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { colors } from "@/components/me/theme";
import { spacing } from "@/src/shared/theme";
import { ListRow } from "@/components/ui/ListRow";
import { getRegistryGroups } from "./registry";
import { usePlatformAdmin } from "./usePlatformAdmin";

export interface RegistryMenuProps {
  /** If supplied, only these group names are rendered (in the order given). */
  groups?: readonly string[];
  /** If true, wraps the whole menu in a ScrollView. Defaults false (parent scrolls). */
  scrollable?: boolean;
}

export function RegistryMenu({
  groups: groupFilter,
  scrollable = false,
}: RegistryMenuProps): React.JSX.Element {
  const router = useRouter();
  const includeStaff = usePlatformAdmin();

  let allGroups = getRegistryGroups({ includeStaff });

  if (groupFilter && groupFilter.length > 0) {
    const filterSet = new Set(groupFilter);
    allGroups = allGroups.filter((g) => filterSet.has(g.name));
    // Preserve caller-specified order
    allGroups = [...allGroups].sort(
      (a, b) =>
        groupFilter.indexOf(a.name) - groupFilter.indexOf(b.name),
    );
  }

  const content = (
    <>
      {allGroups.map((group) => (
        <View key={group.name} style={styles.group}>
          <Text style={styles.groupTitle}>{group.name}</Text>
          {group.screens.map((screen) => (
            <ListRow
              key={screen.route}
              title={screen.title}
              subtitle={screen.subtitle}
              onPress={() => router.push(screen.route as Parameters<typeof router.push>[0])}
              showChevron
              style={styles.row}
            />
          ))}
        </View>
      ))}
    </>
  );

  if (scrollable) {
    return (
      <ScrollView
        contentContainerStyle={styles.container}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
      >
        {content}
      </ScrollView>
    );
  }

  return <View style={styles.container}>{content}</View>;
}

/** Hook returning the registry groups — useful for custom rendering. */
export function useRegistryGroups(groupFilter?: readonly string[]) {
  const includeStaff = usePlatformAdmin();
  let groups = getRegistryGroups({ includeStaff });
  if (groupFilter && groupFilter.length > 0) {
    const filterSet = new Set(groupFilter);
    groups = groups.filter((g) => filterSet.has(g.name));
  }
  return groups;
}

const styles = StyleSheet.create({
  container: { gap: spacing.xl, padding: spacing.lg },
  group: { gap: spacing.sm },
  groupTitle: {
    color: colors.muted,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 1.2,
    textTransform: "uppercase",
    paddingLeft: 2,
  },
  row: { marginBottom: 0 },
});
