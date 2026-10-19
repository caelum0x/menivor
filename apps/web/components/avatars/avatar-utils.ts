import type { Avatar, CustomAvatar } from "@/lib/types";

/** Human-friendly label for an avatar tile / card (falls back to its id). */
export function avatarLabel(
  avatar: Pick<Avatar, "display_name" | "name" | "avatar_id">,
): string {
  return (
    avatar.display_name?.trim() ||
    avatar.name?.trim() ||
    avatar.avatar_id
  );
}

/**
 * Normalize a freshly-created {@link CustomAvatar} (POST /avatars response) into
 * the merged {@link Avatar} shape used by the list + picker, deriving a stable
 * `avatar_id` from the talking-photo id (matching {@link listAvatars}) and
 * tagging it as a preset so it renders with the "Yours" badge. Never mutates the
 * input.
 */
export function customAvatarToAvatar(created: CustomAvatar): Avatar {
  return {
    ...created,
    avatar_id: created.provider_avatar_id?.trim() || created.id,
    source: "preset",
  };
}
