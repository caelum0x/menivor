/**
 * Account · Brand Voices
 *
 * Nav manifest:
 *   { route: "/account/voices",      title: "Brand Voices" }
 *   { route: "/account/voices/[id]", title: "Voice" }
 *
 * The canonical brand-voice screen (/voices and /studio/my-voices redirect
 * here). Clone a new private narrator from a recorded or uploaded sample
 * (POST /api/v1/voices/clone, prepended optimistically), list the caller's
 * cloned voices (GET /api/v1/voices/mine) with pull-to-refresh, and tap any
 * voice to drill into its detail (metadata + sample playback + delete).
 * Explicit loading / error / empty states.
 *
 * Wires endpoints: GET /api/v1/voices/mine, POST /api/v1/voices/clone.
 */

import { useCallback, useState } from "react";
import {
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { useRouter } from "expo-router";

import { cloneVoice, listMyVoices } from "@/lib/api";
import type { CloneVoiceRequest, UserVoice } from "@/lib/types";
import { useSession } from "@/src/shared/auth";

import { Section, SectionState } from "@/components/me/Section";
import { colors } from "@/components/me/theme";
import { useResource } from "@/components/me/use-resource";
import { Icon } from "@/components/ui/Icon";
import { VoiceRecorder } from "@/components/voices/VoiceRecorder";

/** Human status chip label; anything other than "ready" shows the raw state. */
function statusLabel(voice: UserVoice): string {
  return voice.status && voice.status !== "ready" ? voice.status : "Ready";
}

export default function AccountVoicesScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();

  const fetcher = useCallback(() => listMyVoices({ token }), [token]);
  const { status, data, error, reload, setData } =
    useResource<UserVoice[]>(fetcher);
  const [refreshing, setRefreshing] = useState(false);

  const voices = data ?? [];

  const onClone = useCallback(
    async (body: CloneVoiceRequest) => {
      const created = await cloneVoice(body, { token });
      // Prepend the new voice (backend lists newest-first).
      setData((prev) => [created, ...(prev ?? [])]);
    },
    [token, setData],
  );

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const fresh = await listMyVoices({ token });
      setData(() => fresh);
    } catch {
      // keep last-good list
    } finally {
      setRefreshing(false);
    }
  }, [token, setData]);

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={() => void onRefresh()}
          tintColor={colors.accent}
        />
      }
    >
      <Text style={styles.intro}>
        Clone your own voice into a private narrator, then tap a voice to hear
        its sample, copy the selector to use it in a reel, or delete it. Cloned
        voices appear in the “Your voices” group when creating a reel.
      </Text>

      <Section title="NEW VOICE">
        <VoiceRecorder token={token} onClone={onClone} />
      </Section>

      <Section title="YOUR VOICES">
        <SectionState status={status} error={error} onRetry={reload}>
          {voices.length === 0 ? (
            <Text style={styles.empty}>
              No cloned voices yet. Record or upload a short sample above to
              clone your own private narrator.
            </Text>
          ) : (
            <View style={styles.list}>
              {voices.map((voice) => (
                <Pressable
                  key={voice.id}
                  style={styles.card}
                  onPress={() =>
                    router.push({
                      pathname: "/account/voices/[id]",
                      params: { id: voice.id },
                    })
                  }
                  accessibilityRole="button"
                  accessibilityLabel={`Open ${voice.name}`}
                >
                  <View style={styles.body}>
                    <Text style={styles.name} numberOfLines={1}>
                      {voice.name || "Untitled voice"}
                    </Text>
                    <Text style={styles.selector} numberOfLines={1}>
                      {voice.voice_id}
                    </Text>
                  </View>
                  <View style={styles.status}>
                    <Text style={styles.statusText}>{statusLabel(voice)}</Text>
                  </View>
                  <Icon name="chevron-forward" style={styles.chevron} />
                </Pressable>
              ))}
            </View>
          )}
        </SectionState>
      </Section>

      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20, paddingTop: 20 },
  intro: {
    color: colors.textSecondary,
    fontSize: 14,
    lineHeight: 20,
    marginBottom: 16,
  },
  list: { gap: 10 },
  card: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
  },
  body: { flex: 1, gap: 4 },
  name: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  selector: { color: colors.muted, fontSize: 12 },
  status: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  statusText: { color: colors.textSecondary, fontSize: 11, fontWeight: "600" },
  chevron: { color: colors.muted, fontSize: 24, fontWeight: "300" },
  empty: {
    color: colors.muted,
    fontSize: 13,
    lineHeight: 18,
    paddingVertical: 8,
  },
  spacer: { height: 40 },
});
