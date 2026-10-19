/**
 * SPARK — AI Idea Engine screen.
 *
 * A creator describes their app/niche and gets N ready-to-shoot viral UGC
 * concepts. Each concept can be turned into a job in one tap ("Make this",
 * which prefills the Create tab) or saved for later. The lower section lists,
 * re-makes and deletes the caller's saved concepts.
 *
 * Auth token comes from the session and is sent as `x-api-key` by the shared
 * api client. No secrets live here. Generation and the saved-list each own
 * their own loading + error state so a failure in one never blanks the other.
 */

import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { useRouter } from "expo-router";

import {
  deleteSavedIdea,
  generateIdeas,
  listSavedIdeas,
  saveIdea,
} from "@/lib/api";
import { useSession } from "@/src/shared/auth";
import type { GenerateIdeasRequest, Idea, SavedIdea } from "@/lib/types";

import { Section, SectionState } from "@/components/me/Section";
import { describeError } from "@/components/me/errors";
import { useResource } from "@/components/me/use-resource";
import { colors } from "@/components/me/theme";
import { IdeaCard } from "@/components/ideas/IdeaCard";
import { IdeaForm } from "@/components/ideas/IdeaForm";
import { SavedIdeaCard } from "@/components/ideas/SavedIdeaCard";
import { ideaToCreateParams } from "@/components/ideas/make-params";

export default function IdeasScreen() {
  const { apiKey } = useSession();
  const router = useRouter();
  const token = apiKey ?? undefined;

  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);

  const savedFetcher = useCallback(
    () => listSavedIdeas({ token }),
    [token],
  );
  const saved = useResource<SavedIdea[]>(savedFetcher);

  const onGenerate = async (req: GenerateIdeasRequest) => {
    setGenerating(true);
    setGenError(null);
    try {
      const result = await generateIdeas(req, { token });
      setIdeas(result);
      if (result.length === 0) {
        setGenError("No ideas came back — try a more specific description.");
      }
    } catch (err) {
      setGenError(describeError(err, "Failed to generate ideas."));
      setIdeas([]);
    } finally {
      setGenerating(false);
    }
  };

  /** One-click: prefill the Create tab from a concept and navigate there. */
  const onMake = useCallback(
    (idea: Idea) => {
      router.push({
        pathname: "/(tabs)/create",
        params: ideaToCreateParams(idea),
      });
    },
    [router],
  );

  /** Persist a generated concept, then reload the saved list. */
  const onSave = useCallback(
    async (idea: Idea) => {
      await saveIdea(idea, { token });
      saved.reload();
    },
    [token, saved],
  );

  /** Delete a saved concept, optimistically dropping it from the list. */
  const onDelete = useCallback(
    async (id: string) => {
      const previous = saved.data ?? [];
      saved.setData((rows) => (rows ?? []).filter((r) => r.id !== id));
      try {
        await deleteSavedIdea(id, { token });
      } catch (err) {
        // Roll back the optimistic removal on failure.
        saved.setData(() => previous);
        throw err;
      }
    },
    [token, saved],
  );

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
    >
      <Text style={styles.intro}>
        Describe your app or niche and SPARK returns ready-to-shoot viral video
        concepts. Tap “Make this” to jump into the studio prefilled, or save an
        idea for later.
      </Text>

      <IdeaForm loading={generating} onGenerate={onGenerate} />

      {genError ? <Text style={styles.error}>{genError}</Text> : null}

      {generating ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.accent} />
          <Text style={styles.muted}>Generating ideas…</Text>
        </View>
      ) : null}

      {ideas.length > 0 ? (
        <View style={styles.results}>
          <Text style={styles.resultsTitle}>
            {ideas.length} idea{ideas.length === 1 ? "" : "s"}
          </Text>
          {ideas.map((idea, i) => (
            <IdeaCard
              key={`${idea.title || "idea"}-${i}`}
              idea={idea}
              onMake={onMake}
              onSave={onSave}
            />
          ))}
        </View>
      ) : null}

      <View style={styles.divider} />

      <Section
        title="SAVED IDEAS"
        action={
          <Pressable onPress={saved.reload} hitSlop={8}>
            <Text style={styles.refresh}>Refresh</Text>
          </Pressable>
        }
      >
        <SectionState
          status={saved.status}
          error={saved.error}
          onRetry={saved.reload}
          loadingLabel="Loading saved ideas…"
        >
          {saved.data && saved.data.length > 0 ? (
            <View style={styles.savedList}>
              {saved.data.map((row) => (
                <SavedIdeaCard
                  key={row.id}
                  saved={row}
                  onMake={onMake}
                  onDelete={onDelete}
                />
              ))}
            </View>
          ) : (
            <Text style={styles.muted}>
              No saved ideas yet. Generate some above and tap Save.
            </Text>
          )}
        </SectionState>
      </Section>

      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20, paddingTop: 24 },
  intro: { color: colors.textSecondary, fontSize: 14, lineHeight: 20, marginBottom: 16 },
  error: { color: colors.error, fontSize: 14, marginTop: 12 },
  center: { alignItems: "center", justifyContent: "center", paddingVertical: 24, gap: 8 },
  muted: { color: colors.muted, fontSize: 13 },
  results: { gap: 12, marginTop: 20 },
  resultsTitle: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 1.2,
  },
  divider: {
    height: 1,
    backgroundColor: colors.border,
    marginVertical: 28,
  },
  savedList: { gap: 12 },
  refresh: { color: colors.accent, fontWeight: "600", fontSize: 13 },
  spacer: { height: 40 },
});
