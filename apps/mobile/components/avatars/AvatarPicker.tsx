/**
 * AvatarPicker — selectable avatar chips for the create-reel screen. Renders
 * every avatar from GET /avatars (provider catalog + the caller's custom
 * photo→avatars), each with a thumbnail when available, and marks custom ones
 * with a small badge. Selection is by {@link avatarSelectId} — the value the
 * caller sends as `params.avatar_id` (a provider `avatar_id`, or a preset's
 * `provider_avatar_id`). A "＋ From a photo" chip deep-links to the avatars
 * screen to create a new custom avatar.
 */

import {
  Image,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { useRouter } from "expo-router";

import { Icon } from "@/components/ui/Icon";

import { avatarLabel, avatarSelectId, isCustomAvatar, type Avatar } from "@/lib/types";
import { toDisplayUrl } from "@/src/shared/media";

interface AvatarPickerProps {
  avatars: Avatar[];
  /** Currently-selected avatar select-id (`params.avatar_id`), or null. */
  selected: string | null;
  onSelect: (avatarId: string) => void;
  emptyText?: string;
}

export function AvatarPicker({
  avatars,
  selected,
  onSelect,
  emptyText = "No avatars available.",
}: AvatarPickerProps) {
  const router = useRouter();

  return (
    <View style={styles.chips}>
      {avatars.length === 0 ? (
        <Text style={styles.meta}>{emptyText}</Text>
      ) : (
        avatars.map((avatar, index) => {
          const id = avatarSelectId(avatar);
          const active = id === selected;
          const thumb = toDisplayUrl(avatar.thumbnail_url);
          return (
            <Pressable
              key={id || index}
              style={[styles.chip, active && styles.chipActive]}
              onPress={() => onSelect(id)}
              accessibilityRole="button"
              accessibilityState={{ selected: active }}
            >
              {thumb ? (
                <Image
                  source={{ uri: thumb }}
                  style={styles.thumb}
                  resizeMode="cover"
                />
              ) : null}
              <Text style={[styles.chipText, active && styles.chipTextActive]}>
                {avatarLabel(avatar)}
              </Text>
              {isCustomAvatar(avatar) ? (
                <Icon
                  name="star"
                  style={[styles.badge, active && styles.badgeActive]}
                  accessibilityLabel="Custom avatar"
                />
              ) : null}
            </Pressable>
          );
        })
      )}

      <Pressable
        style={styles.createChip}
        onPress={() => router.push("/account/avatars")}
        accessibilityRole="button"
      >
        <Text style={styles.createChipText}>＋ From a photo</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8, alignItems: "center" },
  chip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#0f0f10",
    borderColor: "#27272a",
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  chipActive: { backgroundColor: "#E6C76A", borderColor: "#E6C76A" },
  thumb: { width: 20, height: 20, borderRadius: 10 },
  chipText: { color: "#ece9e1" },
  chipTextActive: { color: "#0f0f10", fontWeight: "700" },
  badge: { color: "#E6C76A", fontSize: 12 },
  badgeActive: { color: "#ece9e1" },
  createChip: {
    backgroundColor: "#0f0f10",
    borderColor: "#E6C76A",
    borderWidth: 1,
    borderStyle: "dashed",
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  createChipText: { color: "#E6C76A", fontWeight: "700" },
  meta: { color: "#6f6c65", fontSize: 13 },
});
