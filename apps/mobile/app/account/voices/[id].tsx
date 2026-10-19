/**
 * Account · Voice Detail
 *
 * Nav manifest: { route: "/account/voices/[id]", title: "Voice" }
 *
 * A single cloned brand voice, resolved from GET /api/v1/voices/mine by its
 * internal row id. There is no single-voice GET, so the screen loads the list
 * and finds the matching row. Shows its metadata (selector — copyable —,
 * status, created date), a sample-playback control when the payload carries a
 * `preview_url`, and a Delete action (DELETE /api/v1/voices/mine/{voice_id})
 * behind a confirmation. Explicit loading / error / not-found states.
 *
 * Wires endpoints: GET /api/v1/voices/mine, DELETE /api/v1/voices/mine/{voice_id}.
 */

import { useCallback, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { Stack, useLocalSearchParams, useRouter } from "expo-router";

import { deleteMyVoice, listMyVoices } from "@/lib/api";
import type { UserVoice } from "@/lib/types";
import { useSession } from "@/src/shared/auth";

import { DetailRows, type DetailRow } from "@/components/account/DetailRows";
import { describeError } from "@/components/me/errors";
import { formatDate } from "@/components/apikeys/format";
import { colors } from "@/components/me/theme";
import { StudioScreen } from "@/components/studio/StudioScreen";
import { useResource } from "@/components/me/use-resource";
import { useAudioPreview } from "@/components/voices/useAudioPreview";

function firstParam(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return value[0] ?? "";
  return value ?? "";
}

/** Defensively read a playable sample URL off the (loosely-typed) voice row. */
function previewUrl(voice: UserVoice | null): string {
  if (!voice) return "";
  const candidate =
    (typeof voice.preview_url === "string" && voice.preview_url) ||
    (typeof voice.sample_url === "string" && voice.sample_url) ||
    "";
  return candidate.trim();
}

export default function AccountVoiceDetailScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();
  const params = useLocalSearchParams<{ id?: string | string[] }>();
  const id = firstParam(params.id).trim();

  const fetcher = useCallback(() => listMyVoices({ token }), [token]);
  const { status, data, error, reload } = useResource<UserVoice[]>(fetcher);
  const preview = useAudioPreview();
  const [deleting, setDeleting] = useState(false);

  const voice = useMemo(
    () => (data ?? []).find((v) => v.id === id) ?? null,
    [data, id],
  );

  const sampleUrl = previewUrl(voice);
  const playing = preview.playingId === id;
  const loadingSample = preview.loadingId === id;

  const rows: DetailRow[] = useMemo(() => {
    if (!voice) return [];
    const out: DetailRow[] = [
      { label: "Selector (voice_name)", value: voice.voice_id, copyable: true, mono: true },
      {
        label: "Status",
        value:
          voice.status && voice.status !== "ready"
            ? voice.status
            : "Ready",
      },
    ];
    const created = formatDate(voice.created_at);
    if (created) out.push({ label: "Created", value: created });
    return out;
  }, [voice]);

  const doDelete = useCallback(async () => {
    setDeleting(true);
    try {
      await preview.stop();
      await deleteMyVoice(id, { token });
      router.back();
    } catch (err) {
      setDeleting(false);
      Alert.alert(
        "Couldn’t delete",
        describeError(err, "Failed to delete this voice."),
      );
    }
  }, [id, token, router, preview]);

  const onDelete = useCallback(() => {
    Alert.alert(
      "Delete this voice?",
      "It will be removed from your narrators and can’t be recovered. Reels already rendered are unaffected.",
      [
        { text: "Keep", style: "cancel" },
        { text: "Delete", style: "destructive", onPress: () => void doDelete() },
      ],
      { cancelable: true },
    );
  }, [doDelete]);

  const name = voice ? voice.name || "Untitled voice" : "Voice";

  return (
    <StudioScreen
      status={status}
      error={error}
      onRetry={reload}
      loadingLabel="Loading voice…"
    >
      <Stack.Screen options={{ title: name }} />
      {!voice ? (
        <View style={styles.notFound}>
          <Text style={styles.notFoundTitle}>Voice not found</Text>
          <Text style={styles.notFoundText}>
            This voice is no longer in your library. It may have been deleted.
          </Text>
          <Pressable
            style={styles.secondary}
            onPress={() => router.back()}
            accessibilityRole="button"
          >
            <Text style={styles.secondaryText}>Back to voices</Text>
          </Pressable>
        </View>
      ) : (
        <ScrollView contentContainerStyle={styles.content}>
          <Text style={styles.title}>{name}</Text>

          <Pressable
            style={[styles.play, (!sampleUrl || loadingSample) && styles.playDisabled]}
            onPress={() => void preview.toggle(id, sampleUrl || undefined)}
            disabled={!sampleUrl || loadingSample}
            accessibilityRole="button"
            accessibilityState={{
              disabled: !sampleUrl || loadingSample,
              selected: playing,
            }}
            accessibilityLabel={playing ? "Pause sample" : "Play sample"}
          >
            {loadingSample ? (
              <ActivityIndicator color={colors.bg} size="small" />
            ) : (
              <Text style={styles.playText}>
                {sampleUrl
                  ? playing
                    ? "Pause sample"
                    : "Play sample"
                  : "No sample available"}
              </Text>
            )}
          </Pressable>
          {preview.error ? (
            <Text style={styles.playError}>{preview.error}</Text>
          ) : null}

          <DetailRows rows={rows} />

          <Pressable
            style={styles.delete}
            onPress={onDelete}
            disabled={deleting}
            accessibilityRole="button"
            accessibilityState={{ disabled: deleting }}
          >
            {deleting ? (
              <ActivityIndicator color={colors.error} size="small" />
            ) : (
              <Text style={styles.deleteText}>Delete voice</Text>
            )}
          </Pressable>
        </ScrollView>
      )}
    </StudioScreen>
  );
}

const styles = StyleSheet.create({
  content: { padding: 16, paddingBottom: 48, gap: 16 },
  title: { color: colors.textPrimary, fontSize: 22, fontWeight: "800" },
  play: {
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
  },
  playDisabled: { backgroundColor: colors.cardAlt },
  playText: { color: colors.bg, fontSize: 15, fontWeight: "700" },
  playError: { color: colors.error, fontSize: 13 },
  delete: {
    borderColor: colors.error,
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 13,
    alignItems: "center",
  },
  deleteText: { color: colors.error, fontSize: 15, fontWeight: "700" },
  notFound: {
    flex: 1,
    padding: 24,
    gap: 12,
    alignItems: "center",
    justifyContent: "center",
  },
  notFoundTitle: { color: colors.textPrimary, fontSize: 18, fontWeight: "700" },
  notFoundText: {
    color: colors.textSecondary,
    fontSize: 14,
    lineHeight: 20,
    textAlign: "center",
  },
  secondary: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
  secondaryText: { color: colors.textSecondary, fontSize: 14, fontWeight: "600" },
});
