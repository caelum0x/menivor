/**
 * Studio · Caption Studio · Caption SEO
 *
 * Nav manifest: { route: "/studio/captions/seo", title: "Caption SEO" }
 *
 * Build a keyword-SEO caption (POST /captions/seo): front-load the words viewers
 * search for and generate platform-specific hashtags from the reel's copy. The
 * source text is seeded from the selected reel's hook via the `seed` route
 * param. Platform picker, an optional base caption, form validation and explicit
 * loading / error states.
 */

import { useCallback, useState } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";

import { useLocalSearchParams } from "expo-router";

import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import {
  CAPTION_PLATFORMS,
  seoCaption,
  type SeoBody,
  type SeoResult,
} from "@/lib/captions";
import { useSession } from "@/src/shared/auth";
import {
  Chips,
  InlineError,
  LabeledInput,
  PrimaryButton,
  SectionCard,
  TagList,
} from "@/components/captions/ui";

export default function CaptionSeoScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const params = useLocalSearchParams<{ seed?: string }>();
  const seed = typeof params.seed === "string" ? params.seed : "";

  const [text, setText] = useState(seed);
  const [platform, setPlatform] = useState<string>(CAPTION_PLATFORMS[0].id);
  const [baseCaption, setBaseCaption] = useState("");
  const [result, setResult] = useState<SeoResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const canSubmit = text.trim().length > 0;

  const run = useCallback(async () => {
    if (!canSubmit) {
      setError("Enter the reel copy to extract keywords from.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const body: SeoBody = {
        text: text.trim(),
        platform,
        base_caption: baseCaption.trim(),
      };
      const res = await seoCaption(body, { token });
      setResult(res);
    } catch (err) {
      setError(describeError(err, "Failed to build the SEO caption."));
    } finally {
      setLoading(false);
    }
  }, [canSubmit, text, platform, baseCaption, token]);

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
    >
      <Text style={styles.intro}>
        Front-load searchable keywords and generate specific hashtags so the caption gets
        indexed on the chosen platform.
      </Text>

      <SectionCard>
        <LabeledInput
          label="Source copy"
          value={text}
          onChangeText={setText}
          placeholder="What the reel is about — script, subject or hook"
          multiline
        />
        <Text style={styles.fieldLabel}>Platform</Text>
        <Chips options={CAPTION_PLATFORMS} selected={platform} onSelect={setPlatform} />
        <LabeledInput
          label="Base caption (optional)"
          value={baseCaption}
          onChangeText={setBaseCaption}
          placeholder="Your own caption to prepend"
          multiline
        />
      </SectionCard>

      <InlineError message={error} />

      <PrimaryButton
        label="Build SEO caption"
        onPress={() => void run()}
        loading={loading}
        disabled={!canSubmit}
      />

      {result ? (
        <View style={styles.resultWrap}>
          <SectionCard title="Caption">
            <Text style={styles.caption}>{result.caption || "—"}</Text>
          </SectionCard>
          <SectionCard title={`Hashtags (${result.hashtags.length})`}>
            {result.hashtags.length > 0 ? (
              <TagList tags={result.hashtags} tone="accent" />
            ) : (
              <Text style={styles.empty}>No hashtags generated.</Text>
            )}
          </SectionCard>
          <SectionCard title={`Keywords (${result.keywords.length})`}>
            {result.keywords.length > 0 ? (
              <TagList tags={result.keywords} tone="muted" />
            ) : (
              <Text style={styles.empty}>No keywords extracted.</Text>
            )}
          </SectionCard>
        </View>
      ) : null}

      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  intro: { color: colors.textSecondary, fontSize: 14, lineHeight: 20, marginBottom: 14 },
  fieldLabel: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  resultWrap: { marginTop: 16 },
  caption: { color: colors.textPrimary, fontSize: 15, lineHeight: 22 },
  empty: { color: colors.muted, fontSize: 13 },
  spacer: { height: 32 },
});
