/**
 * Studio · Voice Library
 *
 * Nav manifest (for the integration agent to wire into navigation):
 *   { route: "/studio/voices",    title: "Voice Library" }
 *   { route: "/studio/my-voices", title: "My Voices" }
 *   { route: "/studio/avatars",   title: "Avatar Gallery" }
 *   { route: "/studio/avatar/[id]", title: "Avatar" }
 *
 * Browse the full narrator catalog (GET /voices): search by name, filter by
 * category, and audition each voice inline (expo-av preview playback, one at a
 * time). "Use" jumps to the create tab. A shortcut card links to the caller's
 * own cloned voices (/studio/my-voices). Pull-to-refresh, plus explicit
 * loading / error / empty states.
 */

import { useCallback, useMemo, useState } from "react";
import {
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { useRouter } from "expo-router";

import { listVoices } from "@/lib/api";
import type { Voice } from "@/lib/types";
import { toDisplayUrl } from "@/src/shared/media";
import { useSession } from "@/src/shared/auth";

import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import { useAudioPreview } from "@/components/voices/useAudioPreview";
import { VoicePreviewCard } from "@/components/voices/VoicePreviewCard";
import { StudioScreen } from "@/components/studio/StudioScreen";
import { FilterChips } from "@/components/studio/FilterChips";

const ALL_CATEGORIES = "__all__";

function voiceCategory(voice: Voice): string {
  return (voice.category || "").trim();
}

export default function StudioVoicesScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();
  const preview = useAudioPreview();

  const [voices, setVoices] = useState<Voice[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<string>(ALL_CATEGORIES);

  const load = useCallback(
    async (mode: "initial" | "refresh") => {
      if (mode === "initial") setStatus("loading");
      else setRefreshing(true);
      try {
        const data = await listVoices({ token });
        setVoices(data);
        setStatus("ready");
        setError("");
      } catch (err) {
        setError(describeError(err, "Failed to load voices."));
        if (mode === "initial") setStatus("error");
      } finally {
        if (mode === "refresh") setRefreshing(false);
      }
    },
    [token],
  );

  const onRefresh = useCallback(() => {
    void preview.stop();
    void load("refresh");
  }, [load, preview]);

  const categories = useMemo(() => {
    const set = new Set<string>();
    for (const v of voices) {
      const c = voiceCategory(v);
      if (c) set.add(c);
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [voices]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return voices.filter((v) => {
      if (category !== ALL_CATEGORIES && voiceCategory(v) !== category) {
        return false;
      }
      if (!q) return true;
      const haystack = [
        v.name ?? "",
        v.voice_id,
        voiceCategory(v),
        ...Object.values(v.labels ?? {}),
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [voices, search, category]);

  const filterOptions = useMemo(
    () => [
      { id: ALL_CATEGORIES, label: "All" },
      ...categories.map((c) => ({ id: c, label: c })),
    ],
    [categories],
  );

  const keyExtractor = useCallback((v: Voice) => v.voice_id, []);

  const renderItem = useCallback(
    ({ item }: { item: Voice }) => {
      const url = toDisplayUrl(voicePreviewUrl(item));
      return (
        <VoicePreviewCard
          voice={item}
          playing={preview.playingId === item.voice_id}
          loading={preview.loadingId === item.voice_id}
          hasPreview={!!url}
          onTogglePreview={() => void preview.toggle(item.voice_id, url)}
          onUse={() => router.push("/(tabs)/create")}
        />
      );
    },
    [preview, router],
  );

  const header = (
    <View style={styles.header}>
      <Text style={styles.intro}>
        Audition every narrator, then use one when creating a reel. Want your own
        cloned voice?
      </Text>
      <Pressable
        style={styles.linkCard}
        onPress={() => router.push("/account/voices")}
        accessibilityRole="button"
      >
        <Text style={styles.linkTitle}>My Voices</Text>
        <Text style={styles.linkSub}>Create, manage and delete cloned voices</Text>
      </Pressable>

      <TextInput
        style={styles.search}
        value={search}
        onChangeText={setSearch}
        placeholder="Search voices"
        placeholderTextColor={colors.muted}
        autoCapitalize="none"
        autoCorrect={false}
        returnKeyType="search"
      />
      {categories.length > 0 ? (
        <FilterChips
          options={filterOptions}
          selected={category}
          onSelect={setCategory}
        />
      ) : null}
      {preview.error ? (
        <Text style={styles.previewError}>{preview.error}</Text>
      ) : null}
      <Text style={styles.count}>
        {filtered.length} {filtered.length === 1 ? "voice" : "voices"}
      </Text>
    </View>
  );

  return (
    <StudioScreen
      status={status}
      error={error}
      onRetry={() => void load("initial")}
      loadingLabel="Loading voices…"
    >
      <FlatList
        data={filtered}
        keyExtractor={keyExtractor}
        renderItem={renderItem}
        ListHeaderComponent={header}
        contentContainerStyle={styles.list}
        ItemSeparatorComponent={Separator}
        ListEmptyComponent={
          <Text style={styles.empty}>
            {voices.length === 0
              ? "No voices are available right now."
              : "No voices match your search."}
          </Text>
        }
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={colors.accent}
          />
        }
        keyboardShouldPersistTaps="handled"
      />
    </StudioScreen>
  );
}

/** Reads a catalog voice's preview URL (`preview_url`). */
function voicePreviewUrl(voice: Voice): string | undefined {
  return typeof voice.preview_url === "string" ? voice.preview_url : undefined;
}

function Separator() {
  return <View style={styles.sep} />;
}

const styles = StyleSheet.create({
  list: { padding: 16, paddingBottom: 48 },
  header: { gap: 12, marginBottom: 12 },
  intro: { color: colors.textSecondary, fontSize: 14, lineHeight: 20 },
  linkCard: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 3,
  },
  linkTitle: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  linkSub: { color: colors.muted, fontSize: 12 },
  search: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    color: colors.textPrimary,
    fontSize: 15,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  previewError: { color: colors.error, fontSize: 13 },
  count: { color: colors.muted, fontSize: 12, fontWeight: "600" },
  sep: { height: 10 },
  empty: {
    color: colors.muted,
    fontSize: 14,
    lineHeight: 20,
    paddingVertical: 24,
    textAlign: "center",
  },
});
