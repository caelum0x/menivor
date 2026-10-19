/**
 * Ad Studio home: paste a product URL (or enter the product by hand), review
 * and edit the drafted ad angles, save the project, and reopen saved projects.
 *
 * The native port of apps/web/src/features/ad-studio/AdStudioHome.tsx +
 * ProjectList.tsx over the same `/v1/ad-studio/*` API.
 */

import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Image,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { useFocusEffect, useRouter } from "expo-router";

import { Button, Icon, Segmented, SelectField, TextField, ToggleField } from "@/components/ui";
import { ApiError, isAbortError } from "@/src/shared/api";
import { useSession } from "@/src/shared/auth";
import { colors, kicker, radius, spacing, typeScale } from "@/src/shared/theme";

import {
  ANGLE_COUNT,
  EMPTY_MANUAL,
  analyzeProduct,
  createAdProject,
  editableAngles,
  listAdProjects,
  manualToInput,
  productToInput,
  validateAnalyze,
  type AdLanguage,
  type AnalyzeInput,
  type AnalyzeResult,
  type ManualDraft,
  type ProjectSummary,
} from "./api";
import { AnglesEditor } from "./components/AnglesEditor";
import { ManualProductForm } from "./components/ManualProductForm";
import { ProductCard } from "./components/ProductCard";

type Mode = "url" | "manual";
type LanguageChoice = "" | AdLanguage;

const LANGUAGE_OPTIONS: readonly { value: LanguageChoice; label: string }[] = [
  { value: "", label: "Match the store" },
  { value: "en", label: "English" },
  { value: "tr", label: "Turkish" },
];

function errorMessage(err: unknown): string {
  if (err instanceof Error && err.message) return err.message;
  return "Something went wrong. Try again.";
}

export function AdStudioHomeScreen() {
  const router = useRouter();
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const [mode, setMode] = useState<Mode>("url");
  const [url, setUrl] = useState("");
  const [manual, setManual] = useState<ManualDraft>(EMPTY_MANUAL);
  const [language, setLanguage] = useState<LanguageChoice>("");
  const [useLlm, setUseLlm] = useState(true);
  const [analysis, setAnalysis] = useState<AnalyzeResult | null>(null);
  const [busy, setBusy] = useState<"" | "analyze" | "save">("");
  const [error, setError] = useState("");

  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [projectsError, setProjectsError] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const loadProjects = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const data = await listAdProjects({ token, signal });
        setProjects(data.projects);
        setProjectsError("");
      } catch (err) {
        if (isAbortError(err)) return;
        setProjectsError(errorMessage(err));
      } finally {
        setRefreshing(false);
      }
    },
    [token],
  );

  // Refresh the saved list whenever the screen regains focus (after a
  // project was renamed, rendered or deleted).
  useFocusEffect(
    useCallback(() => {
      const controller = new AbortController();
      void loadProjects(controller.signal);
      return () => controller.abort();
    }, [loadProjects]),
  );

  const input = (): AnalyzeInput => ({
    ...(mode === "url" ? { url: url.trim() } : { product: manualToInput(manual) }),
    ...(language ? { language } : {}),
    use_llm: useLlm,
    angle_count: ANGLE_COUNT,
  });

  const analyze = async () => {
    const invalid = validateAnalyze(mode, url, manual);
    if (invalid) {
      setError(invalid);
      return;
    }
    setError("");
    setBusy("analyze");
    try {
      setAnalysis(await analyzeProduct(input(), { token }));
    } catch (err) {
      setAnalysis(null);
      setError(errorMessage(err));
      // Stores that block bots (HTTP 424) can still be used with manual details.
      if (err instanceof ApiError && err.status === 424 && mode === "url") {
        setMode("manual");
        setError(
          "This store blocked the automatic read. Enter the product details below instead.",
        );
      }
    } finally {
      setBusy("");
    }
  };

  const save = async () => {
    if (!analysis) return;
    setBusy("save");
    setError("");
    try {
      const project = await createAdProject(
        {
          url: analysis.product.url || undefined,
          product: productToInput(analysis.product),
          use_llm: useLlm,
          language: analysis.language,
          angles: editableAngles(analysis.angles),
        },
        { token },
      );
      setAnalysis(null);
      setUrl("");
      setManual(EMPTY_MANUAL);
      router.push(`/ad-studio/${encodeURIComponent(project.id)}` as never);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  };

  const disabled = busy !== "";

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={() => {
            setRefreshing(true);
            void loadProjects();
          }}
          tintColor={colors.accent}
        />
      }
    >
      <Text style={styles.kicker}>Ad Studio</Text>
      <Text style={styles.title}>Turn a product page into ad variants</Text>
      <Text style={styles.muted}>
        Paste a product link. We read the page, draft five ad angles from its real facts, and
        render them as showcase, before/after or UGC avatar ads in every aspect ratio.
      </Text>

      <View style={styles.card}>
        <Segmented<Mode>
          items={[
            { id: "url", label: "Product link" },
            { id: "manual", label: "Enter manually" },
          ]}
          value={mode}
          onChange={(next) => {
            setMode(next);
            setError("");
          }}
        />
        {mode === "url" ? (
          <TextField
            label="Product URL"
            value={url}
            onChangeText={setUrl}
            placeholder="https://yourstore.com/products/..."
            keyboardType="url"
            autoCapitalize="none"
            editable={!disabled}
            helper="Works with Shopify stores, Amazon, Trendyol and most shops that publish product data. Some stores block automated visits; you can then enter the details manually."
          />
        ) : (
          <ManualProductForm draft={manual} onChange={setManual} disabled={disabled} />
        )}
        <SelectField<LanguageChoice>
          label="Ad language"
          value={language}
          onChange={setLanguage}
          options={LANGUAGE_OPTIONS}
          disabled={disabled}
        />
        <ToggleField
          label="Write copy with AI"
          helper="Falls back to templates if AI is unavailable. Copy only uses facts found on the page."
          value={useLlm}
          onValueChange={setUseLlm}
          disabled={disabled}
        />
        <Button
          label={busy === "analyze" ? "Reading product..." : "Draft ad angles"}
          loading={busy === "analyze"}
          disabled={disabled}
          onPress={() => void analyze()}
        />
        {error && !analysis ? <Text style={styles.error}>{error}</Text> : null}
      </View>

      {analysis ? (
        <View style={styles.section}>
          <ProductCard product={analysis.product} />
          <Text style={styles.sectionTitle}>Ad angles</Text>
          <Text style={styles.muted}>
            Copy uses only facts found on the product page. Edit anything before saving.
          </Text>
          <AnglesEditor
            angles={analysis.angles}
            onChange={(angles) => setAnalysis({ ...analysis, angles })}
            disabled={disabled}
          />
          <Button
            label={busy === "save" ? "Saving and importing images..." : "Save project"}
            loading={busy === "save"}
            disabled={disabled}
            onPress={() => void save()}
          />
          <Button label="Discard" variant="ghost" disabled={disabled} onPress={() => setAnalysis(null)} />
          {error ? <Text style={styles.error}>{error}</Text> : null}
        </View>
      ) : null}

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Your ad projects</Text>
        {projectsError ? (
          <View style={styles.row}>
            <Text style={[styles.error, styles.flex]}>{projectsError}</Text>
            <Button label="Retry" size="sm" variant="secondary" onPress={() => void loadProjects()} />
          </View>
        ) : null}
        {projects === null && !projectsError ? <ActivityIndicator color={colors.accent} /> : null}
        {projects && projects.length === 0 ? (
          <View style={styles.row}>
            <Icon name="megaphone-outline" size={16} color={colors.textSecondary} />
            <Text style={[styles.muted, styles.flex]}>
              No ad projects yet. Paste a product link above to start one.
            </Text>
          </View>
        ) : null}
        {projects?.map((project) => (
          <Pressable
            key={project.id}
            style={styles.projectRow}
            onPress={() => router.push(`/ad-studio/${encodeURIComponent(project.id)}` as never)}
            accessibilityRole="button"
            accessibilityLabel={`Open ${project.title}`}
          >
            {project.thumbnail_url && /^https?:\/\//i.test(project.thumbnail_url) ? (
              <Image source={{ uri: project.thumbnail_url }} style={styles.thumb} resizeMode="contain" />
            ) : (
              <View style={[styles.thumb, styles.thumbEmpty]}>
                <Icon name="image-outline" size={20} color={colors.textSecondary} />
              </View>
            )}
            <View style={styles.flex}>
              <Text style={styles.projectTitle} numberOfLines={2}>
                {project.title}
              </Text>
              <Text style={styles.muted}>
                {project.done_count} of {project.variant_count} ads ready
                {project.created_at ? ` · ${new Date(project.created_at).toLocaleDateString()}` : ""}
              </Text>
            </View>
            <Icon name="chevron-forward" size={18} color={colors.textSecondary} />
          </Pressable>
        ))}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.lg, gap: spacing.md, paddingBottom: 48 },
  kicker,
  title: { color: colors.textPrimary, fontSize: typeScale.heading, fontWeight: "800" },
  card: {
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    gap: spacing.sm,
  },
  section: { gap: spacing.sm, marginTop: spacing.md },
  sectionTitle: { color: colors.textPrimary, fontSize: typeScale.subheading, fontWeight: "700" },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  flex: { flex: 1 },
  muted: { color: colors.textSecondary, fontSize: typeScale.caption, lineHeight: 19 },
  error: { color: colors.danger, fontSize: typeScale.caption, lineHeight: 19 },
  projectRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.sm,
  },
  thumb: {
    width: 64,
    height: 64,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceMuted,
  },
  thumbEmpty: { alignItems: "center", justifyContent: "center" },
  projectTitle: { color: colors.textPrimary, fontSize: typeScale.body, fontWeight: "700" },
});
