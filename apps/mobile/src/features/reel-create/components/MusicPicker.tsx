/**
 * Reel-create list of background-music tracks from GET /catalog/music, with a
 * "No music" option and a simple inline play/pause preview backed by expo-av
 * (`Audio.Sound`). Preview is enabled only when a track exposes a playable URL
 * (the base catalog may not; the field is read defensively via the MusicTrack
 * index signature). Reports the chosen track id upward (null = no music).
 * Handles loading, error, and empty states.
 *
 * When AI-BGM props (`onSelectPrompt`) are supplied AND the backend reports at
 * least one enabled generator (GET /catalog/music-generators), an extra
 * "Generate with AI" option appears: a text prompt (+ optional provider) that
 * sets `music_prompt` / `bgm_provider` on the job and clears the track id. Track
 * selection and the AI prompt are mutually exclusive — choosing one clears the
 * other, matching the backend contract (send `music_id` OR `music_prompt`).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { Audio } from "expo-av";

import { ApiError, listMusic, listMusicGenerators } from "@/lib/api";
import type { MusicGenerator, MusicTrack } from "@/lib/types";
import { Icon } from "@/components/ui/Icon";

interface MusicPickerProps {
  /** Currently-selected track id, or null for "no music" / AI mode. */
  value: string | null;
  onSelect: (musicId: string | null) => void;
  /**
   * Current AI-BGM prompt: `null` when AI mode is not active, otherwise the
   * (possibly empty) prompt text. Only used when `onSelectPrompt` is provided.
   */
  prompt?: string | null;
  /** Current AI-BGM provider id, or `null` to auto-select the first enabled one. */
  provider?: string | null;
  /**
   * Report an AI-BGM selection upward. `prompt === null` clears AI mode; a
   * non-null prompt (even `""`) activates it. Passing this prop is what opts the
   * picker into rendering the "Generate with AI" option (still gated on the
   * backend reporting at least one enabled generator).
   */
  onSelectPrompt?: (prompt: string | null, provider: string | null) => void;
  token?: string;
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; tracks: MusicTrack[] };

/**
 * Read an optional preview URL off a track. The base catalog does not ship one,
 * but the field is honoured defensively so preview lights up automatically if
 * the backend adds it later.
 */
function previewUrlOf(track: MusicTrack): string | null {
  const raw = track.preview_url ?? track.get_url ?? track.url;
  return typeof raw === "string" && raw.length > 0 ? raw : null;
}

function formatDuration(seconds: number | undefined): string | null {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds <= 0) {
    return null;
  }
  const total = Math.round(seconds);
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

export function MusicPicker({
  value,
  onSelect,
  prompt = null,
  provider = null,
  onSelectPrompt,
  token,
}: MusicPickerProps) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [generators, setGenerators] = useState<MusicGenerator[]>([]);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const soundRef = useRef<Audio.Sound | null>(null);

  const load = useCallback(async () => {
    setState({ status: "loading" });
    try {
      const tracks = await listMusic({ token });
      setState({ status: "ready", tracks });
    } catch (err) {
      setState({
        status: "error",
        message:
          err instanceof ApiError
            ? err.message
            : "Could not load music. Please try again.",
      });
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  // Load enabled AI generators best-effort: the "Generate with AI" option only
  // appears when the caller wired `onSelectPrompt` AND the backend reports one.
  // A failure (or an empty list) silently hides the feature — it never blocks
  // the track picker.
  useEffect(() => {
    if (!onSelectPrompt) return;
    let active = true;
    listMusicGenerators({ token })
      .then((list) => {
        if (active) setGenerators(list);
      })
      .catch(() => {
        if (active) setGenerators([]);
      });
    return () => {
      active = false;
    };
  }, [onSelectPrompt, token]);

  const aiAvailable = !!onSelectPrompt && generators.length > 0;
  const aiActive = aiAvailable && prompt !== null;

  // Selecting a catalog track (or "No music") always clears any AI prompt, and
  // vice-versa — the two are mutually exclusive on the job body.
  const selectTrack = useCallback(
    (musicId: string | null) => {
      onSelectPrompt?.(null, null);
      onSelect(musicId);
    },
    [onSelect, onSelectPrompt],
  );

  const enableAi = useCallback(() => {
    if (!onSelectPrompt) return;
    onSelect(null);
    onSelectPrompt(prompt ?? "", provider);
  }, [onSelect, onSelectPrompt, prompt, provider]);

  // Max prompt length: the chosen provider's cap, or the most generous cap among
  // enabled providers when auto-selecting. `0` (unknown) means no client cap —
  // the backend clamps regardless.
  const selectedGen = provider
    ? generators.find((g) => g.id === provider)
    : undefined;
  const maxPromptLength = selectedGen
    ? selectedGen.max_prompt_length
    : generators.reduce((max, g) => Math.max(max, g.max_prompt_length || 0), 0);

  const unload = useCallback(async () => {
    const sound = soundRef.current;
    soundRef.current = null;
    if (sound) {
      try {
        await sound.unloadAsync();
      } catch {
        // best-effort teardown
      }
    }
  }, []);

  // Stop and release audio on unmount.
  useEffect(() => {
    return () => {
      void unload();
    };
  }, [unload]);

  const togglePreview = useCallback(
    async (track: MusicTrack) => {
      const url = previewUrlOf(track);
      if (!url) return;

      // Tapping the currently-playing track stops it.
      if (playingId === track.id) {
        await unload();
        setPlayingId(null);
        return;
      }

      await unload();
      try {
        const { sound } = await Audio.Sound.createAsync(
          { uri: url },
          { shouldPlay: true },
        );
        soundRef.current = sound;
        setPlayingId(track.id);
        sound.setOnPlaybackStatusUpdate((status) => {
          if (status.isLoaded && status.didJustFinish) {
            setPlayingId(null);
          }
        });
      } catch {
        setPlayingId(null);
      }
    },
    [playingId, unload],
  );

  if (state.status === "loading") {
    return (
      <View style={styles.center}>
        <ActivityIndicator color="#E6C76A" />
      </View>
    );
  }

  if (state.status === "error") {
    return (
      <View style={styles.center}>
        <Text style={styles.error}>{state.message}</Text>
        <Pressable style={styles.retry} onPress={() => void load()}>
          <Text style={styles.retryText}>Retry</Text>
        </Pressable>
      </View>
    );
  }

  const noMusic = value === null && !aiActive;

  return (
    <View style={styles.wrap}>
      {/* "No music" option — background music is optional. */}
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ selected: noMusic }}
        style={[styles.rowItem, noMusic && styles.rowItemActive]}
        onPress={() => selectTrack(null)}
      >
        <View style={styles.iconStub}>
          <Icon name="close" style={styles.iconStubText} />
        </View>
        <View style={styles.rowText}>
          <Text style={styles.trackName}>No background music</Text>
          <Text style={styles.trackMeta}>Keep only the narration audio.</Text>
        </View>
        {noMusic ? <Icon name="checkmark" style={styles.check} /> : null}
      </Pressable>

      {state.tracks.length === 0 ? (
        <Text style={styles.empty}>No music tracks are available yet.</Text>
      ) : (
        <FlatList
          data={state.tracks}
          scrollEnabled={false}
          keyExtractor={(item) => item.id}
          ItemSeparatorComponent={() => <View style={styles.sep} />}
          renderItem={({ item }) => {
            const selected = item.id === value;
            const isPlaying = playingId === item.id;
            const url = previewUrlOf(item);
            const duration = formatDuration(item.duration_s);
            return (
              <View style={[styles.rowItem, selected && styles.rowItemActive]}>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel={
                    !url
                      ? `No preview for ${item.name}`
                      : isPlaying
                        ? `Pause ${item.name}`
                        : `Play ${item.name}`
                  }
                  disabled={!url}
                  style={[styles.playBtn, !url && styles.playBtnDisabled]}
                  onPress={() => void togglePreview(item)}
                >
                  <Icon
                    name={!url ? "musical-note" : isPlaying ? "pause" : "play"}
                    style={styles.playIcon}
                  />
                </Pressable>

                <Pressable
                  accessibilityRole="button"
                  accessibilityState={{ selected }}
                  style={styles.rowText}
                  onPress={() => selectTrack(item.id)}
                >
                  <Text style={styles.trackName} numberOfLines={1}>
                    {item.name}
                  </Text>
                  {duration ? (
                    <Text style={styles.trackMeta}>{duration}</Text>
                  ) : null}
                </Pressable>

                {selected ? <Icon name="checkmark" style={styles.check} /> : null}
              </View>
            );
          }}
        />
      )}

      {aiAvailable ? (
        <>
          <Pressable
            accessibilityRole="button"
            accessibilityState={{ selected: aiActive }}
            style={[styles.rowItem, aiActive && styles.rowItemActive]}
            onPress={enableAi}
          >
            <View style={styles.iconStub}>
              <Text style={styles.iconStubText}>AI</Text>
            </View>
            <View style={styles.rowText}>
              <Text style={styles.trackName}>Generate with AI</Text>
              <Text style={styles.trackMeta}>
                Describe the vibe — a custom royalty-free track is composed for
                you.
              </Text>
            </View>
            {aiActive ? <Icon name="checkmark" style={styles.check} /> : null}
          </Pressable>

          {aiActive ? (
            <View style={styles.aiPanel}>
              {generators.length > 1 ? (
                <View style={styles.providerRow}>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityState={{ selected: provider === null }}
                    style={[
                      styles.providerChip,
                      provider === null && styles.providerChipActive,
                    ]}
                    onPress={() => onSelectPrompt?.(prompt ?? "", null)}
                  >
                    <Text
                      style={[
                        styles.providerChipText,
                        provider === null && styles.providerChipTextActive,
                      ]}
                    >
                      Auto
                    </Text>
                  </Pressable>
                  {generators.map((g) => {
                    const active = provider === g.id;
                    return (
                      <Pressable
                        key={g.id}
                        accessibilityRole="button"
                        accessibilityState={{ selected: active }}
                        style={[
                          styles.providerChip,
                          active && styles.providerChipActive,
                        ]}
                        onPress={() => onSelectPrompt?.(prompt ?? "", g.id)}
                      >
                        <Text
                          style={[
                            styles.providerChipText,
                            active && styles.providerChipTextActive,
                          ]}
                        >
                          {g.name}
                        </Text>
                      </Pressable>
                    );
                  })}
                </View>
              ) : null}

              <TextInput
                style={styles.aiInput}
                value={prompt ?? ""}
                onChangeText={(text) => onSelectPrompt?.(text, provider)}
                placeholder="e.g. upbeat lo-fi hip hop, mellow, no vocals"
                placeholderTextColor="#6f6c65"
                multiline
                maxLength={maxPromptLength > 0 ? maxPromptLength : undefined}
              />
              {maxPromptLength > 0 ? (
                <Text style={styles.counter}>
                  {(prompt ?? "").length}/{maxPromptLength}
                </Text>
              ) : null}
            </View>
          ) : null}
        </>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 8 },
  center: { paddingVertical: 20, alignItems: "center", gap: 10 },
  rowItem: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    backgroundColor: "#0f0f10",
    borderColor: "#27272a",
    borderWidth: 1,
    borderRadius: 10,
    padding: 12,
  },
  rowItemActive: { borderColor: "#E6C76A" },
  sep: { height: 8 },
  iconStub: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: "#27272a",
    alignItems: "center",
    justifyContent: "center",
  },
  iconStubText: { color: "#6f6c65", fontSize: 16 },
  playBtn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: "#27272a",
    alignItems: "center",
    justifyContent: "center",
  },
  playBtnDisabled: { opacity: 0.5 },
  playIcon: { color: "#ece9e1", fontSize: 14 },
  rowText: { flex: 1, minWidth: 0 },
  trackName: { color: "#ece9e1", fontSize: 14, fontWeight: "600" },
  trackMeta: { color: "#6f6c65", fontSize: 12, marginTop: 2 },
  check: { color: "#E6C76A", fontSize: 18, fontWeight: "800" },
  aiPanel: { gap: 8, paddingHorizontal: 4 },
  providerRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  providerChip: {
    backgroundColor: "#0f0f10",
    borderColor: "#27272a",
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 6,
  },
  providerChipActive: { borderColor: "#E6C76A", backgroundColor: "#1d1a33" },
  providerChipText: { color: "#ece9e1", fontSize: 13, fontWeight: "600" },
  providerChipTextActive: { color: "#ece9e1" },
  aiInput: {
    backgroundColor: "#0f0f10",
    borderColor: "#27272a",
    borderWidth: 1,
    borderRadius: 10,
    padding: 12,
    color: "#ece9e1",
    fontSize: 14,
    minHeight: 72,
    textAlignVertical: "top",
  },
  counter: {
    color: "#6f6c65",
    fontSize: 12,
    textAlign: "right",
  },
  error: { color: "#E0847F", fontSize: 14, textAlign: "center" },
  empty: { color: "#6f6c65", fontSize: 13 },
  retry: {
    backgroundColor: "#0f0f10",
    borderColor: "#27272a",
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  retryText: { color: "#ece9e1", fontWeight: "600" },
});
