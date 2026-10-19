import type { LucideIcon } from "lucide-react";
import { Instagram, Music2, Share2, Youtube } from "lucide-react";
import {
  SOCIAL_CONNECTION_PROVIDERS,
  type SocialProvider,
} from "@/lib/types";

/**
 * Display metadata for the social providers a reel can be connected to /
 * published to. `SOCIAL_CONNECTION_PROVIDERS` (from lib/types) mirrors the
 * backend allow-list and is the source of truth for which providers exist; this
 * module only adds presentation (label + icon). An unknown provider still
 * renders via {@link providerLabel} / {@link providerIcon} fallbacks so a
 * forward-compatible backend addition never breaks the UI.
 */
export interface ProviderMeta {
  id: SocialProvider;
  label: string;
  icon: LucideIcon;
}

const META: Record<
  (typeof SOCIAL_CONNECTION_PROVIDERS)[number],
  Omit<ProviderMeta, "id">
> = {
  tiktok: { label: "TikTok", icon: Music2 },
  instagram: { label: "Instagram", icon: Instagram },
  youtube: { label: "YouTube", icon: Youtube },
};

/** Ordered provider metadata for rendering the known providers. */
export const PROVIDER_OPTIONS: readonly ProviderMeta[] =
  SOCIAL_CONNECTION_PROVIDERS.map((id) => ({ id, ...META[id] }));

/** Human label for a provider id, falling back to a Title-cased raw id. */
export function providerLabel(id: SocialProvider): string {
  const known = META[id as (typeof SOCIAL_CONNECTION_PROVIDERS)[number]];
  if (known) return known.label;
  const raw = String(id);
  return raw ? raw.charAt(0).toUpperCase() + raw.slice(1) : raw;
}

/** Icon for a provider id, falling back to a generic share glyph. */
export function providerIcon(id: SocialProvider): LucideIcon {
  return (
    META[id as (typeof SOCIAL_CONNECTION_PROVIDERS)[number]]?.icon ?? Share2
  );
}
