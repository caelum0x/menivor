/**
 * useAudioPreview — a tiny single-track audio player for previewing voice
 * samples (catalog `preview_url`s and cloned-voice previews). Only ONE sound
 * plays at a time: starting a new preview unloads the previous one. Owns the
 * expo-av `Audio.Sound` lifecycle, exposes which id is currently loading /
 * playing, and always unloads on unmount.
 *
 * The iOS audio session is put into `playsInSilentModeIOS` so a preview is
 * audible even with the ringer switch off.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { Audio, type AVPlaybackStatus } from "expo-av";

import { describeError } from "@/components/me/errors";

export interface AudioPreview {
  /** Id of the track currently playing, or null. */
  playingId: string | null;
  /** Id of the track currently loading (buffering before playback), or null. */
  loadingId: string | null;
  /** Last playback error, or null. */
  error: string | null;
  /**
   * Toggle a track by a caller-stable id: plays it (unloading any other), or
   * stops it if it is already the active track. A blank/invalid `url` surfaces
   * a friendly error instead of throwing.
   */
  toggle: (id: string, url: string | undefined) => Promise<void>;
  /** Stop + unload whatever is playing (no-op when idle). */
  stop: () => Promise<void>;
}

export function useAudioPreview(): AudioPreview {
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const soundRef = useRef<Audio.Sound | null>(null);
  // A monotonically increasing token guards against races when the user taps
  // several previews quickly: only the newest load may set state.
  const loadTokenRef = useRef(0);

  const unload = useCallback(async () => {
    const active = soundRef.current;
    soundRef.current = null;
    if (active) {
      try {
        await active.stopAsync();
      } catch {
        /* best-effort */
      }
      try {
        await active.unloadAsync();
      } catch {
        /* best-effort */
      }
    }
  }, []);

  const stop = useCallback(async () => {
    loadTokenRef.current += 1;
    await unload();
    setPlayingId(null);
    setLoadingId(null);
  }, [unload]);

  const toggle = useCallback(
    async (id: string, url: string | undefined) => {
      setError(null);

      // Tapping the active track stops it.
      if (playingId === id || loadingId === id) {
        await stop();
        return;
      }

      const trimmed = (url ?? "").trim();
      if (!/^https?:\/\//i.test(trimmed)) {
        setError("No preview is available for this voice.");
        return;
      }

      const token = ++loadTokenRef.current;
      setLoadingId(id);
      // Unload any currently-playing track before starting the new one.
      await unload();
      setPlayingId(null);

      try {
        await Audio.setAudioModeAsync({ playsInSilentModeIOS: true }).catch(
          () => {
            /* non-fatal */
          },
        );

        const onStatus = (status: AVPlaybackStatus): void => {
          if (!status.isLoaded) return;
          if (status.didJustFinish) {
            // Playback reached the end — reset only if still the active track.
            if (loadTokenRef.current === token) {
              soundRef.current = null;
              setPlayingId(null);
            }
          }
        };

        const { sound } = await Audio.Sound.createAsync(
          { uri: trimmed },
          { shouldPlay: true },
          onStatus,
        );

        // A newer toggle superseded us while loading — discard this sound.
        if (loadTokenRef.current !== token) {
          try {
            await sound.unloadAsync();
          } catch {
            /* best-effort */
          }
          return;
        }

        soundRef.current = sound;
        setLoadingId(null);
        setPlayingId(id);
      } catch (err) {
        if (loadTokenRef.current === token) {
          setLoadingId(null);
          setPlayingId(null);
          setError(describeError(err, "Could not play this preview."));
        }
      }
    },
    [playingId, loadingId, stop, unload],
  );

  useEffect(() => {
    return () => {
      loadTokenRef.current += 1;
      const active = soundRef.current;
      soundRef.current = null;
      if (active) {
        active.unloadAsync().catch(() => {
          /* best-effort cleanup */
        });
      }
    };
  }, []);

  return { playingId, loadingId, error, toggle, stop };
}
