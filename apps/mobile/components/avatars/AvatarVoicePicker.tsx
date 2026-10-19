/**
 * AvatarVoicePicker — optional default-narrator selector for a new custom
 * avatar. Loads the ElevenLabs catalog (GET /voices) and the caller's cloned
 * brand voices (GET /voices/mine) and lets them pin one as the avatar's default
 * `voice_name` (`"elevenlabs:<voice_id>"`), or leave it unset ("No default").
 *
 * Voice selection is optional: an avatar with no default voice simply uses
 * whatever narrator the creator picks per reel.
 */

import { useCallback } from "react";
import { StyleSheet, Text, View } from "react-native";

import { listMyVoices, listVoices } from "@/lib/api";
import type { UserVoice, Voice } from "@/lib/types";

import { SectionState } from "@/components/me/Section";
import { colors } from "@/components/me/theme";
import { useResource } from "@/components/me/use-resource";

/** Narrator-selector prefix handled by the backend's ElevenLabs TTS branch. */
const ELEVENLABS_PREFIX = "elevenlabs:";

/** Full narrator selector for a catalog voice (`elevenlabs:<voice_id>`). */
function catalogSelector(voice: Voice): string {
  return `${ELEVENLABS_PREFIX}${voice.voice_id}`;
}

interface VoicesData {
  catalog: Voice[];
  mine: UserVoice[];
}

interface AvatarVoicePickerProps {
  token: string | undefined;
  /** Currently-selected narrator selector, or null for no default. */
  value: string | null;
  onSelect: (selector: string | null) => void;
  disabled?: boolean;
}

interface Chip {
  id: string | null;
  label: string;
}

export function AvatarVoicePicker({
  token,
  value,
  onSelect,
  disabled = false,
}: AvatarVoicePickerProps) {
  const fetcher = useCallback(async (): Promise<VoicesData> => {
    const [catalog, mine] = await Promise.all([
      listVoices({ token }).catch(() => [] as Voice[]),
      listMyVoices({ token }).catch(() => [] as UserVoice[]),
    ]);
    return { catalog, mine };
  }, [token]);

  const { status, data, error, reload } = useResource<VoicesData>(fetcher);

  const chips: Chip[] = [{ id: null, label: "No default" }];
  for (const v of data?.catalog ?? []) {
    chips.push({ id: catalogSelector(v), label: v.name || v.voice_id });
  }
  for (const v of data?.mine ?? []) {
    chips.push({ id: v.voice_id, label: v.name || v.voice_id });
  }

  return (
    <SectionState
      status={status}
      error={error}
      onRetry={reload}
      loadingLabel="Loading voices…"
    >
      <View style={styles.chips}>
        {chips.map((chip) => {
          const active = chip.id === value;
          return (
            <Text
              key={chip.id ?? "__none__"}
              accessibilityRole="button"
              accessibilityState={{ selected: active, disabled }}
              onPress={disabled ? undefined : () => onSelect(chip.id)}
              style={[
                styles.chip,
                active && styles.chipActive,
                disabled && styles.chipDisabled,
              ]}
            >
              {chip.label}
            </Text>
          );
        })}
      </View>
    </SectionState>
  );
}

const styles = StyleSheet.create({
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    overflow: "hidden",
    color: colors.textSecondary,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 8,
    fontSize: 13,
  },
  chipActive: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
    color: colors.textPrimary,
    fontWeight: "700",
  },
  chipDisabled: { opacity: 0.5 },
});
