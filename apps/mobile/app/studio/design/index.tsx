/**
 * Route: /studio/design — minimal mobile Design Studio. Pick a size, a
 * template and a brand kit, describe the post, and get layout options in your
 * brand (live previews). Save one as a design, or start from a template you
 * saved. Your designs are listed below; open one to edit its text and export.
 *
 * Backed by GET /design/templates, GET /design/brand-kits, POST /design/generate,
 * GET /design/docs and POST /design/docs — the web's /studio/design domain.
 */

import { useCallback, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Image,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
  useWindowDimensions,
} from "react-native";
import { Stack, useFocusEffect, useRouter } from "expo-router";

import { DesignPreview } from "@/components/design-studio/DesignPreview";
import { Button, Chip, EmptyState, ErrorState, TextField } from "@/components/ui";
import {
  MAX_PROMPT_CHARS,
  SIZE_LABELS,
  createDesign,
  generateDesigns,
  listBrandKits,
  listDesignTemplates,
  listDesigns,
  orderOptions,
  templatesForSize,
  validatePrompt,
  type BrandKitInfo,
  type DesignSummary,
  type GenerateResult,
  type GeneratedOption,
  type SizePreset,
  type TemplateInfo,
} from "@/lib/design-studio";
import { readableApiMessage } from "@/lib/social-inbox";
import { ApiError } from "@/src/shared/api";
import { useSession } from "@/src/shared/auth";
import { colors, radius, spacing, typeScale } from "@/src/shared/theme";

function describe(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 429) return "Too many requests. Wait a minute and try again.";
    if (err.status === 503) return "Design Studio is unavailable right now.";
    return readableApiMessage(err.message, fallback);
  }
  return err instanceof Error ? err.message : fallback;
}

export default function DesignStudioScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();
  const { width: screenWidth } = useWindowDimensions();
  const previewWidth = Math.min(screenWidth - spacing.lg * 2, 420);

  const [sizes, setSizes] = useState<SizePreset[]>([]);
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [kits, setKits] = useState<BrandKitInfo[]>([]);
  const [designs, setDesigns] = useState<DesignSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [size, setSize] = useState("square");
  const [templateSlug, setTemplateSlug] = useState("");
  const [kitId, setKitId] = useState<string | null>(null);
  const [prompt, setPrompt] = useState("");
  const [result, setResult] = useState<GenerateResult | null>(null);
  const [busy, setBusy] = useState<"" | "generate" | string>("");
  const [formError, setFormError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const [tpl, brand, docs] = await Promise.all([
        listDesignTemplates({ token }),
        listBrandKits({ token }).catch(() => ({ kits: [] as BrandKitInfo[] })),
        listDesigns({ token }).catch(() => ({ designs: [] as DesignSummary[], total: 0 })),
      ]);
      setSizes(tpl.sizes);
      setTemplates(tpl.templates);
      setKits(brand.kits);
      setDesigns(docs.designs);
    } catch (err) {
      setLoadError(describe(err, "Could not load Design Studio."));
    }
  }, [token]);

  useFocusEffect(
    useCallback(() => {
      let active = true;
      setLoading(true);
      load().finally(() => {
        if (active) setLoading(false);
      });
      return () => {
        active = false;
      };
    }, [load]),
  );

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  const sizeTemplates = useMemo(() => templatesForSize(templates, size), [templates, size]);
  const builtins = sizeTemplates.filter((t) => t.builtin);
  const saved = sizeTemplates.filter((t) => !t.builtin && t.id);
  const options = useMemo(
    () => (result ? orderOptions(result.options, templateSlug) : []),
    [result, templateSlug],
  );

  const onGenerate = useCallback(async () => {
    const checked = validatePrompt(prompt);
    if (!checked.ok) {
      setFormError(checked.error);
      return;
    }
    setBusy("generate");
    setFormError(null);
    try {
      setResult(await generateDesigns({ prompt: checked.prompt, size_preset: size, brand_kit_id: kitId }, { token }));
    } catch (err) {
      setFormError(describe(err, "Could not generate layouts."));
    } finally {
      setBusy("");
    }
  }, [kitId, prompt, size, token]);

  const onUseOption = useCallback(
    async (option: GeneratedOption) => {
      if (!result) return;
      setBusy(option.template);
      setFormError(null);
      try {
        const doc = await createDesign(
          {
            size_preset: result.size_preset,
            canvas: option.canvas,
            template: option.template,
            brand_kit_id: result.brand.brand_kit_id,
            prompt: prompt.trim(),
          },
          { token },
        );
        router.push({ pathname: "/studio/design/[id]", params: { id: doc.id } });
      } catch (err) {
        setFormError(describe(err, "Could not save the design."));
      } finally {
        setBusy("");
      }
    },
    [prompt, result, router, token],
  );

  const onUseSaved = useCallback(
    async (template: TemplateInfo) => {
      if (!template.id) return;
      setBusy(template.id);
      setFormError(null);
      try {
        const doc = await createDesign(
          { size_preset: template.presets[0] || size, template_id: template.id, title: template.name, brand_kit_id: kitId },
          { token },
        );
        router.push({ pathname: "/studio/design/[id]", params: { id: doc.id } });
      } catch (err) {
        setFormError(describe(err, "Could not start from that template."));
      } finally {
        setBusy("");
      }
    },
    [kitId, router, size, token],
  );

  if (loading && sizes.length === 0) {
    return (
      <View style={styles.center}>
        <Stack.Screen options={{ title: "Design Studio" }} />
        <ActivityIndicator color={colors.accent} />
      </View>
    );
  }

  if (loadError && sizes.length === 0) {
    return (
      <View style={styles.center}>
        <Stack.Screen options={{ title: "Design Studio" }} />
        <ErrorState message={loadError} onRetry={load} />
      </View>
    );
  }

  return (
    <ScrollView
      style={styles.flex}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />}
    >
      <Stack.Screen options={{ title: "Design Studio" }} />
      <Text style={styles.lead}>
        Static posts, stories, banners and store screenshots in your brand. Describe the post, pick a layout, then
        edit the text.
      </Text>

      <Text style={styles.section}>Size</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
        {sizes.map((s) => (
          <Chip
            key={s.id}
            label={`${SIZE_LABELS[s.id] ?? s.id} · ${s.width}x${s.height}`}
            active={size === s.id}
            onPress={() => {
              setSize(s.id);
              setTemplateSlug("");
              setResult(null);
            }}
          />
        ))}
      </ScrollView>

      <Text style={styles.section}>Template</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
        <Chip label="Any" active={templateSlug === ""} onPress={() => setTemplateSlug("")} />
        {builtins.map((t) => (
          <Chip key={t.slug} label={t.name} active={templateSlug === t.slug} onPress={() => setTemplateSlug(t.slug)} />
        ))}
      </ScrollView>
      {saved.length > 0 ? (
        <>
          <Text style={styles.faint}>Your saved templates start a design right away</Text>
          <View style={styles.wrap}>
            {saved.map((t) => (
              <Button
                key={t.id ?? t.slug}
                label={t.name}
                variant="secondary"
                size="sm"
                loading={busy === t.id}
                disabled={busy !== ""}
                onPress={() => onUseSaved(t)}
              />
            ))}
          </View>
        </>
      ) : null}

      <Text style={styles.section}>Brand kit</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
        <Chip label="Default brand" active={kitId === null} onPress={() => setKitId(null)} />
        {kits.map((k) => (
          <Chip key={k.id} label={k.name} active={kitId === k.id} onPress={() => setKitId(k.id)} />
        ))}
      </ScrollView>

      <TextField
        label="What is the post about?"
        value={prompt}
        onChangeText={setPrompt}
        placeholder="Launch day: our app now exports 4K reels"
        multiline
        numberOfLines={3}
        maxLength={MAX_PROMPT_CHARS}
      />
      {formError ? <Text style={styles.error}>{formError}</Text> : null}
      <Button
        label={result ? "Generate again" : "Generate layouts"}
        loading={busy === "generate"}
        disabled={busy !== ""}
        onPress={onGenerate}
      />

      {result ? (
        <>
          <Text style={styles.faint}>
            {result.copy_source === "llm" ? "Copy written by AI" : "Copy from your description"}
            {result.brand.has_brand ? ` · ${result.brand.name}` : ""}
          </Text>
          {options.map((option) => (
            <View key={option.template} style={styles.option}>
              <Text style={styles.optionTitle}>{option.name}</Text>
              {option.canvas.pages[0] ? (
                <DesignPreview
                  page={option.canvas.pages[0]}
                  width={result.width}
                  height={result.height}
                  maxWidth={previewWidth}
                  maxHeight={previewWidth * 1.4}
                  token={token}
                />
              ) : null}
              <Button
                label="Use this layout"
                size="sm"
                loading={busy === option.template}
                disabled={busy !== ""}
                onPress={() => onUseOption(option)}
              />
            </View>
          ))}
        </>
      ) : null}

      <Text style={styles.section}>Your designs</Text>
      {designs.length === 0 ? (
        <EmptyState title="No designs yet" body="Generate a layout above and save it to start one." />
      ) : (
        designs.map((d) => (
          <Pressable
            key={d.id}
            style={({ pressed }) => [styles.designRow, pressed && styles.pressed]}
            onPress={() => router.push({ pathname: "/studio/design/[id]", params: { id: d.id } })}
            accessibilityRole="button"
            accessibilityLabel={`Open ${d.title}`}
          >
            {d.thumb_url ? (
              <Image source={{ uri: d.thumb_url }} style={styles.thumb} resizeMode="cover" />
            ) : (
              <View style={[styles.thumb, styles.thumbEmpty]} />
            )}
            <View style={styles.designBody}>
              <Text style={styles.designTitle} numberOfLines={1}>
                {d.title}
              </Text>
              <Text style={styles.faint}>
                {SIZE_LABELS[d.size_preset] ?? d.size_preset} · {d.page_count} page{d.page_count === 1 ? "" : "s"} ·{" "}
                {d.status === "draft" ? "Draft" : d.status === "exported" ? "Exported" : "Scheduled"}
              </Text>
            </View>
          </Pressable>
        ))
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bg },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.bg, padding: spacing.lg },
  content: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xxl },
  lead: { color: colors.textSecondary, fontSize: typeScale.caption, lineHeight: 19 },
  section: { color: colors.textPrimary, fontSize: typeScale.subheading, fontWeight: "700", marginTop: spacing.sm },
  chips: { gap: spacing.sm, paddingRight: spacing.lg },
  wrap: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  faint: { color: colors.textFaint, fontSize: typeScale.micro },
  error: { color: colors.danger, fontSize: typeScale.caption },
  option: {
    gap: spacing.sm,
    padding: spacing.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    alignItems: "flex-start",
  },
  optionTitle: { color: colors.textPrimary, fontSize: typeScale.body, fontWeight: "600" },
  designRow: {
    flexDirection: "row",
    gap: spacing.md,
    alignItems: "center",
    padding: spacing.sm,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
  },
  pressed: { opacity: 0.7 },
  thumb: { width: 56, height: 56, borderRadius: radius.sm },
  thumbEmpty: { backgroundColor: colors.surfaceAlt },
  designBody: { flex: 1, gap: 2 },
  designTitle: { color: colors.textPrimary, fontSize: typeScale.body, fontWeight: "600" },
});
