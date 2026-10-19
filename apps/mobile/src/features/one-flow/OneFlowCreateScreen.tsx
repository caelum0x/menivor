/**
 * The default Create tab: one box (topic or product/page link), one format
 * choice, one button. It starts three reel variants with different opening
 * hooks on the existing `POST /jobs` pipeline and hands off to
 * `/create/results`, which tracks each variant live. Every run is registered
 * as a 1-body/N-hooks experiment so the remake-winner loop tracks it.
 *
 * The native port of apps/web/src/features/create-compose/one-flow/
 * OneFlowCreate.tsx; the request logic lives in ./plan (shared, unit-tested).
 *
 * Presenter, voice and language have working defaults pulled from the live
 * catalogs and sit behind a collapsed section, so the first run is one tap.
 * The full wizard (screen recording, music, captions, workspaces) stays one
 * tap away at /create/advanced.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { useRouter } from "expo-router";

import { Button, Icon, SelectField, TextField } from "@/components/ui";
import {
  ApiError,
  createJob,
  ingestUrl,
  isAbortError,
  listAvatars,
  listBackgrounds,
  listVoices,
  me,
} from "@/lib/api";
import {
  avatarSelectId,
  type Avatar,
  type BackgroundClip,
  type Language,
  type Voice,
} from "@/lib/types";
import { useSession } from "@/src/shared/auth";
import { useGenerationCapabilities } from "@/src/shared/hooks";
import { WaitlistHome } from "@/src/shared/product";
import { colors, kicker, radius, spacing, typeScale } from "@/src/shared/theme";

import {
  CREATE_PRESETS,
  CREDITS_PER_REEL,
  MAX_INPUT_LENGTH,
  VARIANT_COUNT,
  buildJobRequest,
  buildRunRegistration,
  defaultPresetFor,
  defaultVoiceFor,
  describeCreateError,
  findPreset,
  hostOf,
  missingCatalogParts,
  parseSource,
  pickBackground,
  planLinkVariants,
  resolvePreset,
  resultsHref,
  topicRunVariants,
  voiceIdOf,
  type PresetId,
} from "./plan";
import { registerRun } from "./run-api";
import { saveRun, type RunVariantMeta } from "./run-store";
import { isRouteAvailable } from "@/src/shared/release/surface";

export interface OneFlowCreateScreenProps {
  /** Prefill from `/(tabs)/create?q=`. */
  readonly initialInput?: string;
  /** Prefill from `/(tabs)/create?preset=`. */
  readonly initialPreset?: string;
}

interface Catalog {
  readonly avatars: readonly Avatar[];
  readonly voices: readonly Voice[];
  readonly backgrounds: readonly BackgroundClip[];
}

type CatalogState =
  | { readonly status: "loading" }
  | { readonly status: "error"; readonly message: string }
  | { readonly status: "ready"; readonly catalog: Catalog };

type SubmitPhase = "idle" | "reading" | "starting";

const LANGUAGE_OPTIONS: readonly { value: Language; label: string }[] = [
  { value: "auto", label: "Match the topic" },
  { value: "en", label: "English" },
  { value: "tr", label: "Turkish" },
];

function friendlyError(err: unknown): string {
  if (err instanceof ApiError) return describeCreateError(err.status, err.message);
  if (err instanceof Error) return describeCreateError(undefined, err.message);
  return describeCreateError(undefined, "");
}

function avatarLabel(avatar: Avatar | undefined): string {
  if (!avatar) return "";
  return avatar.display_name || avatar.name || avatarSelectId(avatar);
}

function voiceLabel(voice: Voice | undefined): string {
  if (!voice) return "";
  return voice.name || voiceIdOf(voice);
}

export function OneFlowCreateScreen({
  initialInput = "",
  initialPreset,
}: OneFlowCreateScreenProps) {
  const router = useRouter();
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const capabilityState = useGenerationCapabilities(token);
  const admitted = capabilityState.capabilities?.generation.reels === true;

  const [input, setInput] = useState(initialInput);
  const parsed = parseSource(input);
  const initialPresetId = findPreset(initialPreset)?.id;
  const [presetId, setPresetId] = useState<PresetId>(
    initialPresetId ?? defaultPresetFor(parseSource(initialInput)?.kind ?? "topic"),
  );
  const [presetTouched, setPresetTouched] = useState(Boolean(initialPresetId));
  const [language, setLanguage] = useState<Language>("auto");
  const [avatarId, setAvatarId] = useState("");
  const [voiceId, setVoiceId] = useState("");
  const [showVoices, setShowVoices] = useState(false);
  const [catalog, setCatalog] = useState<CatalogState>({ status: "loading" });
  const [catalogNonce, setCatalogNonce] = useState(0);
  const [credits, setCredits] = useState<number | null>(null);
  const [phase, setPhase] = useState<SubmitPhase>("idle");
  const [error, setError] = useState("");

  // Follow the input: a link suggests the product ad, a topic the presenter,
  // until the creator picks a format themselves.
  const parsedKind = parsed?.kind;
  useEffect(() => {
    if (presetTouched || !parsedKind) return;
    setPresetId(defaultPresetFor(parsedKind));
  }, [parsedKind, presetTouched]);

  useEffect(() => {
    if (!admitted) return;
    const controller = new AbortController();
    const options = { token, signal: controller.signal };
    setCatalog({ status: "loading" });
    Promise.all([listAvatars(options), listVoices(options), listBackgrounds(undefined, options)])
      .then(([avatars, voices, backgrounds]) => {
        const usableAvatars = avatars.filter(
          (avatar) => avatar.is_active !== false && avatarSelectId(avatar) !== "",
        );
        const usableVoices = (Array.isArray(voices) ? voices : []).filter((v) => voiceIdOf(v));
        setCatalog({
          status: "ready",
          catalog: { avatars: usableAvatars, voices: usableVoices, backgrounds },
        });
        const firstAvatar = usableAvatars[0];
        setAvatarId((prev) => prev || (firstAvatar ? avatarSelectId(firstAvatar) : ""));
        setVoiceId((prev) => prev || defaultVoiceFor(firstAvatar?.voice_name, usableVoices));
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted || isAbortError(err)) return;
        setCatalog({ status: "error", message: friendlyError(err) });
      });
    // Non-blocking: the create call itself reports a credit shortfall.
    me(options)
      .then((profile) => setCredits(profile.credits))
      .catch(() => undefined);
    return () => controller.abort();
  }, [admitted, token, catalogNonce]);

  const preset = resolvePreset(presetId);
  const catalogReady = catalog.status === "ready" ? catalog.catalog : null;
  const backgroundId = catalogReady
    ? pickBackground(catalogReady.backgrounds, preset.preferredBackground)
    : "";
  const missing = useMemo(
    () =>
      catalogReady
        ? missingCatalogParts({
            needsPresenter: preset.needsPresenter,
            avatarCount: catalogReady.avatars.length,
            voiceCount: catalogReady.voices.length,
            backgroundId,
          })
        : [],
    [backgroundId, catalogReady, preset.needsPresenter],
  );
  const needed = VARIANT_COUNT * CREDITS_PER_REEL;
  const notEnoughCredits = credits !== null && credits < needed;
  const busy = phase !== "idle";
  const canSubmit =
    parsed !== null &&
    catalogReady !== null &&
    missing.length === 0 &&
    (!preset.needsPresenter || avatarId !== "") &&
    voiceId !== "" &&
    !notEnoughCredits &&
    !busy;

  const submit = useCallback(async () => {
    if (!canSubmit || !parsed) return;
    setError("");
    const startedAt = Date.now();
    const base = { layout: preset.layout, avatarId, voiceId, backgroundId, language };
    try {
      let variants: RunVariantMeta[] = [];
      let notice: string | undefined;
      let batchId: string | undefined;

      if (parsed.kind === "topic") {
        setPhase("starting");
        const result = await createJob(
          buildJobRequest({ ...base, subject: parsed.value, variants: VARIANT_COUNT }),
          { token },
        );
        // The API assigns each variant its own hook angle and registers the
        // batch as an experiment itself.
        variants = topicRunVariants(result);
        batchId = result.batch_id || undefined;
      } else {
        setPhase("reading");
        const page = await ingestUrl(parsed.value, { token });
        const subject =
          page.reel_draft?.video_subject || page.content?.title || hostOf(parsed.value);
        const plans = planLinkVariants(
          {
            title: page.content?.title || subject,
            description: page.content?.description ?? "",
            features: page.content?.features ?? [],
          },
          language,
        );
        setPhase("starting");
        for (const plan of plans) {
          try {
            const result = await createJob(
              buildJobRequest({ ...base, subject, script: plan.script, variants: 1, hookStyle: plan.angle }),
              { token },
            );
            variants = [...variants, { jobId: result.job_id, angle: plan.angle, hook: plan.hook }];
          } catch (err) {
            // Nothing started yet: surface the error here. Otherwise continue
            // to the results with what did start.
            if (variants.length === 0) throw err;
            notice = `${variants.length} of ${VARIANT_COUNT} variants started. ${friendlyError(err)}`;
            break;
          }
        }
        // Link the separately started reels into one hook experiment. The
        // reels render either way, so a failure here is reported, not thrown.
        const registration = buildRunRegistration(variants);
        if (registration) {
          try {
            const run = await registerRun(registration, { token });
            batchId = run.batch_id || undefined;
          } catch (err) {
            const linkNotice = `Your reels are rendering, but they could not be linked for hook tracking: ${friendlyError(err)}`;
            notice = notice ? `${notice} ${linkNotice}` : linkNotice;
          }
        }
      }

      await saveRun({
        source: parsed.kind,
        input: parsed.value,
        presetId: preset.id,
        startedAt,
        variants,
        ...(batchId ? { batchId } : {}),
        ...(notice ? { notice } : {}),
      });
      setPhase("idle");
      setInput("");
      router.push(resultsHref(variants.map((variant) => variant.jobId)) as never);
    } catch (err) {
      setError(friendlyError(err));
      setPhase("idle");
    }
  }, [avatarId, backgroundId, canSubmit, language, parsed, preset, router, token, voiceId]);

  if (capabilityState.loading) {
    return <CenteredNote label="Preparing your studio..." spinner />;
  }
  if (!admitted) {
    return <WaitlistHome token={token} source="mobile-create" />;
  }

  const selectedAvatar =
    catalogReady?.avatars.find((a) => avatarSelectId(a) === avatarId) ?? catalogReady?.avatars[0];
  const selectedVoice =
    catalogReady?.voices.find((v) => voiceIdOf(v) === voiceId) ?? catalogReady?.voices[0];

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
    >
      <Text style={styles.kicker}>01 / Make 3 reels</Text>
      <Text style={styles.title}>What is the reel about?</Text>

      <TextField
        value={input}
        onChangeText={setInput}
        placeholder="A topic (why most people quit the gym in week 3) or a link (https://yourshop.com/products/...)"
        multiline
        numberOfLines={3}
        maxLength={MAX_INPUT_LENGTH}
        editable={!busy}
        autoCapitalize="sentences"
        helper={
          parsed?.kind === "link"
            ? `Link detected. We'll read ${hostOf(parsed.value)} and write three hooks from what's on the page.`
            : parsed
              ? "Topic detected. The script writer drafts three versions that open differently: a POV hook, a question, and a what-nobody-tells-you hook."
              : "Paste a product or page link, or type a topic."
        }
      />

      <Text style={styles.sectionLabel}>Format</Text>
      <View style={styles.presets} accessibilityRole="radiogroup">
        {CREATE_PRESETS.map((option) => {
          const selected = option.id === preset.id;
          return (
            <Pressable
              key={option.id}
              onPress={() => {
                setPresetId(option.id);
                setPresetTouched(true);
              }}
              disabled={busy}
              accessibilityRole="radio"
              accessibilityState={{ checked: selected, disabled: busy }}
              style={[styles.preset, selected && styles.presetSelected]}
            >
              <View style={styles.presetHead}>
                <Text style={styles.presetTitle}>{option.title}</Text>
                {selected ? <Icon name="checkmark-circle" size={18} color={colors.accent} /> : null}
              </View>
              <Text style={styles.presetBlurb}>{option.blurb}</Text>
            </Pressable>
          );
        })}
      </View>

      {catalog.status === "loading" ? (
        <CenteredNote label="Loading presenters and voices..." spinner />
      ) : null}
      {catalog.status === "error" ? (
        <View style={styles.notice}>
          <Text style={styles.errorText}>{catalog.message}</Text>
          <Button label="Retry" variant="secondary" size="sm" onPress={() => setCatalogNonce((n) => n + 1)} />
        </View>
      ) : null}

      {catalogReady && missing.length > 0 ? (
        <View style={styles.notice}>
          <Text style={styles.body}>
            This server doesn&apos;t have {missing.join(", ")} set up yet, so this format
            can&apos;t render right now.
          </Text>
          {missing.length === 1 && missing[0] === "an AI presenter" ? (
            <>
              <Text style={styles.muted}>
                The faceless story needs no presenter: a narrator voice reads the script over
                background footage.
              </Text>
              <Button
                label="Use the faceless story"
                variant="secondary"
                size="sm"
                onPress={() => {
                  setPresetId("faceless");
                  setPresetTouched(true);
                }}
              />
            </>
          ) : (
            <>
              <Text style={styles.muted}>
                You can still make a captioned reel from your own recording and narration in the
                full editor.
              </Text>
              <Button
                label="Open the full editor"
                variant="secondary"
                size="sm"
                onPress={() => router.push("/create/advanced" as never)}
              />
            </>
          )}
        </View>
      ) : null}

      {catalogReady && missing.length === 0 ? (
        <View style={styles.voiceCard}>
          <Pressable
            onPress={() => setShowVoices((open) => !open)}
            accessibilityRole="button"
            accessibilityState={{ expanded: showVoices }}
            style={styles.voiceHead}
          >
            <View style={styles.flex}>
              <Text style={styles.voiceTitle}>
                {preset.needsPresenter ? "Presenter and voice" : "Narrator voice"}
              </Text>
              <Text style={styles.muted} numberOfLines={1}>
                {preset.needsPresenter ? `${avatarLabel(selectedAvatar)} · ` : ""}
                {voiceLabel(selectedVoice)}
              </Text>
            </View>
            <Icon
              name={showVoices ? "chevron-up" : "chevron-down"}
              size={18}
              color={colors.textSecondary}
            />
          </Pressable>
          {showVoices ? (
            <View style={styles.voiceBody}>
              {preset.needsPresenter ? (
                <SelectField
                  label="Presenter"
                  value={avatarId}
                  disabled={busy}
                  options={catalogReady.avatars.map((a) => ({
                    value: avatarSelectId(a),
                    label: avatarLabel(a),
                  }))}
                  onChange={(value) => {
                    setAvatarId(value);
                    const avatar = catalogReady.avatars.find((a) => avatarSelectId(a) === value);
                    const paired = defaultVoiceFor(avatar?.voice_name, catalogReady.voices);
                    if (avatar?.voice_name && paired) setVoiceId(paired);
                  }}
                />
              ) : null}
              <SelectField
                label="Voice"
                value={voiceId}
                disabled={busy}
                options={catalogReady.voices.map((v) => ({ value: voiceIdOf(v), label: voiceLabel(v) }))}
                onChange={setVoiceId}
              />
              <SelectField<Language>
                label="Language"
                value={language}
                disabled={busy}
                options={LANGUAGE_OPTIONS}
                onChange={setLanguage}
              />
            </View>
          ) : null}
        </View>
      ) : null}

      <View style={styles.costRow}>
        <Icon name="flash-outline" size={16} color={colors.textSecondary} />
        <Text style={[styles.muted, styles.flex]}>
          Uses {needed} credits, {CREDITS_PER_REEL} per reel.
          {credits !== null ? ` You have ${credits}.` : ""} A failed render refunds its credit
          automatically.
        </Text>
      </View>

      <Button
        label={
          phase === "reading"
            ? "Reading the page..."
            : phase === "starting"
              ? `Starting ${VARIANT_COUNT} renders...`
              : `Make ${VARIANT_COUNT} reels`
        }
        size="lg"
        loading={busy}
        disabled={!canSubmit}
        onPress={() => void submit()}
        accessibilityLabel={`Make ${VARIANT_COUNT} reels`}
      />

      {notEnoughCredits ? (
        <View style={styles.notice}>
          <Text style={styles.body}>
            Three reels need {needed} credits. Credits never expire, and a failed render is
            refunded automatically.
          </Text>
          <View style={styles.row}>
            <Button label="Get credits" size="sm" onPress={() => router.push("/wallet/top-up" as never)} />
            {isRouteAvailable("/insights/referral") ? (
              <Button
                label="Invite a friend"
                variant="secondary"
                size="sm"
                onPress={() => router.push("/insights/referral" as never)}
              />
            ) : null}
          </View>
        </View>
      ) : null}

      {error ? (
        <View style={styles.notice} accessibilityRole="alert">
          <Text style={styles.errorText}>{error}</Text>
          {error.includes("credits") ? (
            <Button label="Get credits" size="sm" onPress={() => router.push("/wallet/top-up" as never)} />
          ) : null}
        </View>
      ) : null}

      <View style={styles.links}>
        <Pressable
          onPress={() => router.push("/create/advanced" as never)}
          accessibilityRole="link"
          hitSlop={8}
          style={styles.linkRow}
        >
          <Icon name="options-outline" size={16} color={colors.textSecondary} />
          <Text style={styles.link}>Full editor: screen recording, music, captions</Text>
        </Pressable>
        <Pressable
          onPress={() => router.push("/ad-studio" as never)}
          accessibilityRole="link"
          hitSlop={8}
          style={styles.linkRow}
        >
          <Icon name="megaphone-outline" size={16} color={colors.textSecondary} />
          <Text style={styles.link}>Ad Studio: turn a product page into ad variants</Text>
        </Pressable>
        {isRouteAvailable("/insights/winners") ? (
          <Pressable
            onPress={() => router.push("/insights/winners" as never)}
            accessibilityRole="link"
            hitSlop={8}
            style={styles.linkRow}
          >
            <Icon name="trophy-outline" size={16} color={colors.textSecondary} />
            <Text style={styles.link}>Winners: see which hook won and remake it</Text>
          </Pressable>
        ) : null}
      </View>
    </ScrollView>
  );
}

function CenteredNote({ label, spinner = false }: Readonly<{ label: string; spinner?: boolean }>) {
  return (
    <View style={styles.center}>
      {spinner ? <ActivityIndicator color={colors.accent} /> : null}
      <Text style={styles.muted}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.lg, gap: spacing.md, paddingBottom: 48 },
  kicker,
  title: { color: colors.textPrimary, fontSize: typeScale.heading, fontWeight: "800" },
  sectionLabel: {
    color: colors.textSecondary,
    fontSize: typeScale.caption,
    fontWeight: "700",
    marginTop: spacing.sm,
  },
  presets: { gap: spacing.sm },
  preset: {
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    gap: spacing.xs,
  },
  presetSelected: { borderColor: colors.accent },
  presetHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  presetTitle: { color: colors.textPrimary, fontSize: typeScale.body, fontWeight: "700" },
  presetBlurb: { color: colors.textSecondary, fontSize: typeScale.caption, lineHeight: 18 },
  voiceCard: {
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
  },
  voiceHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm, padding: spacing.md },
  voiceTitle: { color: colors.textPrimary, fontSize: typeScale.body, fontWeight: "700" },
  voiceBody: { paddingHorizontal: spacing.md, paddingBottom: spacing.md, gap: spacing.sm },
  notice: {
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceAlt,
    borderRadius: radius.lg,
    padding: spacing.md,
    gap: spacing.sm,
  },
  costRow: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm, marginTop: spacing.sm },
  row: { flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" },
  flex: { flex: 1 },
  body: { color: colors.textPrimary, fontSize: typeScale.caption, lineHeight: 19 },
  muted: { color: colors.textSecondary, fontSize: typeScale.caption, lineHeight: 19 },
  errorText: { color: colors.danger, fontSize: typeScale.caption, lineHeight: 19 },
  links: { gap: spacing.md, marginTop: spacing.lg, borderTopWidth: 1, borderTopColor: colors.border, paddingTop: spacing.lg },
  linkRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  link: { color: colors.textSecondary, fontSize: typeScale.caption, fontWeight: "600", textDecorationLine: "underline" },
  center: { alignItems: "center", justifyContent: "center", gap: spacing.sm, paddingVertical: spacing.xl },
});
