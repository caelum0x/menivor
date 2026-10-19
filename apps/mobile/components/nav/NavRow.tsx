/**
 * NavRow — a registry screen rendered as a navigable row with an optional live
 * badge and a pin toggle. Wraps the shared {@link ListRow} primitive so it
 * inherits the editorial styling. No emoji: the pin uses a text glyph.
 */

import { Pressable, StyleSheet, Text, View } from "react-native";

import { Badge } from "@/components/ui/Badge";
import { ListRow } from "@/components/ui/ListRow";
import { colors } from "@/components/me/theme";
import { spacing } from "@/src/shared/theme";
import type { ScreenMeta } from "@/lib/nav/registry";
import type { RowBadge } from "@/lib/nav/badges";
import { Icon } from "@/components/ui/Icon";

export interface NavRowProps {
  screen: ScreenMeta;
  /** Optional caption shown above the title (e.g. the group name in search). */
  caption?: string;
  badge?: RowBadge | null;
  pinned?: boolean;
  onOpen: (route: string) => void;
  onTogglePin?: (route: string) => void;
}

export function NavRow({
  screen,
  caption,
  badge,
  pinned = false,
  onOpen,
  onTogglePin,
}: NavRowProps): React.JSX.Element {
  const trailing = (
    <View style={styles.trailing}>
      {badge ? <Badge label={badge.label} variant={badge.variant} /> : null}
      {onTogglePin ? (
        <Pressable
          onPress={() => onTogglePin(screen.route)}
          accessibilityRole="button"
          accessibilityLabel={pinned ? "Unpin screen" : "Pin screen"}
          accessibilityState={{ selected: pinned }}
          hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
          style={styles.pin}
        >
          <Text style={[styles.pinGlyph, pinned && styles.pinGlyphOn]}>
            {pinned ? "Pinned" : "Pin"}
          </Text>
        </Pressable>
      ) : null}
      <Icon name="chevron-forward" style={styles.chevron} />
    </View>
  );

  return (
    <View>
      {caption ? <Text style={styles.caption}>{caption}</Text> : null}
      <ListRow
        title={screen.title}
        subtitle={screen.subtitle}
        onPress={() => onOpen(screen.route)}
        trailing={trailing}
        highlighted={pinned}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  trailing: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  pin: { paddingHorizontal: 2 },
  pinGlyph: {
    color: colors.muted,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.6,
    textTransform: "uppercase",
  },
  pinGlyphOn: { color: colors.accent },
  chevron: { color: colors.muted, fontSize: 22, fontWeight: "700" },
  caption: {
    color: colors.muted,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 1,
    textTransform: "uppercase",
    marginBottom: 4,
    paddingLeft: 2,
  },
});
