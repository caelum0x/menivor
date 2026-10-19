"use client";

import * as React from "react";
import {
  ApiError,
  listAvatars,
  listCaptionStyles,
  listLayouts,
  listMusic,
  listVoices,
} from "@/lib/api";
import type {
  Avatar,
  CaptionStyle,
  LayoutOption,
  MusicTrack,
  Voice,
} from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import type { PresetLabelMaps } from "@/components/presets/preset-config";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

/** The catalog data needed to render + label the preset config form. */
export interface PresetCatalogs {
  captionStyles: readonly CaptionStyle[];
  music: readonly MusicTrack[];
  layouts: readonly LayoutOption[];
  avatars: readonly Avatar[];
  voices: readonly Voice[];
}

const EMPTY_CATALOGS: PresetCatalogs = {
  captionStyles: [],
  music: [],
  layouts: [],
  avatars: [],
  voices: [],
};

export type CatalogsStatus = "loading" | "ready" | "error";

export interface UseCatalogsResult {
  status: CatalogsStatus;
  catalogs: PresetCatalogs;
  /** id → display-name maps derived from the catalogs, for summaries. */
  labelMaps: PresetLabelMaps;
  errorMessage: string;
  reload: () => void;
}

function avatarLabel(avatar: Avatar): string {
  return avatar.display_name || avatar.name || avatar.avatar_id;
}

function voiceLabel(voice: Voice): string {
  return voice.name || voice.voice_id;
}

/**
 * Loads the read-only catalogs (caption styles, music, layouts, avatars,
 * voices) used by the preset form, plus id→label maps for summaries. Each
 * catalog is fetched independently and degrades to an empty list on failure so
 * a single missing catalog never blocks the form; a hard error only surfaces
 * when every catalog fails.
 */
export function useCatalogs(): UseCatalogsResult {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<CatalogsStatus>("loading");
  const [catalogs, setCatalogs] = React.useState<PresetCatalogs>(EMPTY_CATALOGS);
  const [errorMessage, setErrorMessage] = React.useState("");

  const load = React.useCallback(async () => {
    setStatus("loading");
    setErrorMessage("");
    try {
      const token = await getApiToken();
      const options = { token };
      const [captionStyles, music, layouts, avatars, voices] =
        await Promise.all([
          listCaptionStyles(options).catch(() => [] as CaptionStyle[]),
          listMusic(options).catch(() => [] as MusicTrack[]),
          listLayouts(options).catch(() => [] as LayoutOption[]),
          listAvatars(options).catch(() => [] as Avatar[]),
          listVoices(options).catch(() => [] as Voice[]),
        ]);
      setCatalogs({ captionStyles, music, layouts, avatars, voices });
      setStatus("ready");
    } catch (err) {
      const message =
        friendlyErrorMessage(err, "Couldn't load the catalog options.");
      setErrorMessage(message);
      setStatus("error");
    }
  }, [getApiToken]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const labelMaps = React.useMemo<PresetLabelMaps>(
    () => ({
      caption: Object.fromEntries(
        catalogs.captionStyles.map((c) => [c.id, c.name]),
      ),
      music: Object.fromEntries(catalogs.music.map((m) => [m.id, m.name])),
      layout: Object.fromEntries(catalogs.layouts.map((l) => [l.id, l.name])),
    }),
    [catalogs],
  );

  return {
    status,
    catalogs,
    labelMaps,
    errorMessage,
    reload: () => void load(),
  };
}

export { avatarLabel, voiceLabel };
