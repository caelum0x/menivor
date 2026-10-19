import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
} from "react-native";

import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";

import {
  ApiError,
  createJob,
  listAvatars,
  listMyVoices,
  listMyWorkspaces,
  listVoices,
  presignAndUpload,
  type LocalFile,
} from "@/lib/api";
import {
  JobVideo,
  loadAttachedBrollKey,
  pickRecordingFromFiles,
  pickRecordingFromLibrary,
  saveAttachedBrollKey,
} from "@/src/shared/media";
import { useSession } from "@/src/shared/auth";
import { useGenerationCapabilities } from "@/src/shared/hooks";
import { isBrollAvailable } from "@/src/features/broll-studio/availability";
import { colors } from "@/src/shared/theme";
import { formatUsdMicros } from "@/lib/marketplace";
import { useLastQuote } from "@/lib/model-quote";
import {
  CreatorFlowRail,
  WaitlistHome,
  discardDraft,
  draftMediaAvailable,
  getDraft,
  type CreatorFlowStage,
} from "@/src/shared/product";
import {
  CAMERA_MOTIONS,
  CAMERA_MOTION_LABELS,
  DEFAULT_CAMERA_MOTION,
  LAYOUTS,
  avatarSelectId,
  type Avatar,
  type CameraMotion,
  type Language,
  type Layout,
  type JobCreateRequest,
  type Template,
  type UserVoice,
  type Voice,
  type Workspace,
} from "@/lib/types";

import { AvatarPicker } from "@/components/avatars/AvatarPicker";
import { CaptionStylePicker } from "./components/CaptionStylePicker";
import { MusicPicker } from "./components/MusicPicker";
import { TemplatesRow } from "./components/TemplatesRow";
import { VariantsStepper } from "./components/VariantsStepper";
import { WorkspaceSelect } from "@/components/team/WorkspaceSelect";
import { VoiceoverPicker } from "@/components/voiceover/VoiceoverPicker";
import { GenerationErrorNotice } from "@/components/billing/GenerationErrorNotice";
import { isRouteAvailable } from "@/src/shared/release/surface";

type Phase = "idle" | "uploading" | "submitting";

const DEFAULT_CAPTION_STYLE = "default";
const DEFAULT_DURATION_S = 30;
const LANGUAGES: readonly Language[] = ["auto", "tr", "en"];

/** Narrator-selector prefix handled by the backend's ElevenLabs TTS branch. */
const ELEVENLABS_PREFIX = "elevenlabs:";

/** The full narrator selector for a catalog voice (`elevenlabs:<voice_id>`). */
function catalogSelector(voice: Voice): string {
  return `${ELEVENLABS_PREFIX}${voice.voice_id}`;
}

/** Strip the `elevenlabs:` prefix to recover the raw provider voice id. */
function providerVoiceId(selector: string): string {
  return selector.startsWith(ELEVENLABS_PREFIX)
    ? selector.slice(ELEVENLABS_PREFIX.length)
    : selector;
}

/** Narrow a free-form template value to a known Layout, else keep current. */
function coerceLayout(value: Layout | string, fallback: Layout): Layout {
  return (LAYOUTS as readonly string[]).includes(value)
    ? (value as Layout)
    : fallback;
}

/** Read the first value of a route param that may arrive as string | string[]. */
function first(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return value[0] ?? "";
  return value ?? "";
}

/** Narrow a free-form template value to a known Language, else "auto". */
function coerceLanguage(value: Language | string): Language {
  return (LANGUAGES as readonly string[]).includes(value)
    ? (value as Language)
    : "auto";
}

/**
 * The full reel wizard: screen recording, custom script, avatar and voice,
 * music, caption style, variants and workspace billing. Mounted at
 * /create/advanced, and in place on the Create tab when a deep link carries
 * wizard params (Spark prefill, drafts, imported footage, B-roll). The Create
 * tab itself defaults to the one-flow (src/features/one-flow).
 */
export function CreateScreen() {
  const { apiKey } = useSession();
  const router = useRouter();
  const token = apiKey ?? undefined;
  const capabilityState = useGenerationCapabilities(token);
  const generationAllowed =
    capabilityState.capabilities?.generation.reels === true;
  const brollAvailable = isBrollAvailable(capabilityState.capabilities);
  // Pre-render cost estimate assembled in the Model Catalog (device-local).
  const { quote: lastQuote, reload: reloadQuote } = useLastQuote();

  const [subject, setSubject] = useState("");
  /** Optional narration script; only shown/sent when prefilled from Spark. */
  const [script, setScript] = useState("");
  const [file, setFile] = useState<LocalFile | null>(null);
  const [recordingKey, setRecordingKey] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [phase, setPhase] = useState<Phase>("idle");

  const [avatars, setAvatars] = useState<Avatar[]>([]);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [myVoices, setMyVoices] = useState<UserVoice[]>([]);
  const [avatarId, setAvatarId] = useState<string | null>(null);
  /** Full narrator selector (`elevenlabs:<id>`) for the picked voice. */
  const [voiceName, setVoiceName] = useState<string | null>(null);
  // BRING YOUR OWN VOICEOVER (BYOV): when `useOwnVoiceover` is on, the creator's
  // uploaded narration (`voiceoverKey`) replaces TTS and the voice pickers are
  // hidden. TTS stays the default (off). See `params.voiceover_key`.
  const [useOwnVoiceover, setUseOwnVoiceover] = useState(false);
  const [voiceoverKey, setVoiceoverKey] = useState<string | null>(null);
  const [layout, setLayout] = useState<Layout>("pip");

  // Creator-studio fields.
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [captionStyle, setCaptionStyle] = useState<string>(
    DEFAULT_CAPTION_STYLE,
  );
  const [musicId, setMusicId] = useState<string | null>(null);
  // AI background music: `musicPrompt === null` means AI mode is off; a non-null
  // (possibly empty) prompt activates it. `bgmProvider === null` lets the backend
  // auto-select the first enabled provider. Mutually exclusive with `musicId`.
  const [musicPrompt, setMusicPrompt] = useState<string | null>(null);
  const [bgmProvider, setBgmProvider] = useState<string | null>(null);
  const [variants, setVariants] = useState<number>(1);
  const [language, setLanguage] = useState<Language>("auto");
  const [durationS, setDurationS] = useState<number>(DEFAULT_DURATION_S);
  // Opt-in dead-air auto-cut: pre-trims silent/static gaps from the screen
  // recording before compose. Off by default; sent as top-level `auto_tighten`.
  const [autoTighten, setAutoTighten] = useState(false);
  // Editing polish (all opt-in, default-off, applied to the SCREEN recording
  // pre-compose): scene-driven punch-in zoom (`auto_zoom`), a camera-motion
  // preset (`camera_motion`; "none" = off), and neural avatar background matting
  // (`remove_bg`). Each is duration-preserving + degrade-safe; the voiceover and
  // caption timeline is never touched.
  const [autoZoom, setAutoZoom] = useState(false);
  const [cameraMotion, setCameraMotion] =
    useState<CameraMotion>(DEFAULT_CAMERA_MOTION);
  const [removeBg, setRemoveBg] = useState(false);

  // "Charge to" — the caller's workspaces + the picked billing target. `null`
  // means charge the caller's personal credits; a workspace id charges its
  // shared pool.
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [chargeWorkspaceId, setChargeWorkspaceId] = useState<string | null>(
    null,
  );

  const [error, setError] = useState<string | null>(null);
  /** True once a SPARK "Make this" prefill has been applied to the form. */
  const [fromSpark, setFromSpark] = useState(false);
  const [brollIntroKey, setBrollIntroKey] = useState<string | null>(null);

  // One-click "Make this" prefill from the Spark screen, passed as route params.
  const params = useLocalSearchParams<{
    prefill?: string | string[];
    subject?: string | string[];
    script?: string | string[];
    layout?: string | string[];
    caption_style?: string | string[];
    language?: string | string[];
    broll_key?: string | string[];
    /** Resume a device-local draft (brief + clip) saved while waiting. */
    draft?: string | string[];
    /** Footage already uploaded elsewhere (Capture > Import). */
    recording_key?: string | string[];
    recording_name?: string | string[];
  }>();
  /** Draft being resumed; discarded once its job is created. */
  const resumedDraftRef = useRef<string | null>(null);
  const appliedDraftRef = useRef<string | null>(null);
  const appliedImportRef = useRef<string | null>(null);
  /** Display name for footage attached by key (no local file to preview). */
  const [importedName, setImportedName] = useState<string | null>(null);
  const appliedPrefillRef = useRef<string | null>(null);
  const pendingCreateRef = useRef<
    { fingerprint: string; idempotencyKey: string } | undefined
  >(undefined);

  useEffect(() => {
    if (first(params.prefill) !== "1") return;

    // Apply each distinct prefill exactly once so it never clobbers later edits.
    const signature = JSON.stringify([
      first(params.subject),
      first(params.script),
      first(params.layout),
      first(params.caption_style),
      first(params.language),
    ]);
    if (appliedPrefillRef.current === signature) return;
    appliedPrefillRef.current = signature;

    const subjectParam = first(params.subject);
    if (subjectParam) setSubject(subjectParam);
    const scriptParam = first(params.script);
    if (scriptParam) setScript(scriptParam);
    const layoutParam = first(params.layout);
    if (layoutParam) setLayout(coerceLayout(layoutParam, "pip"));
    const captionParam = first(params.caption_style);
    if (captionParam) setCaptionStyle(captionParam);
    const languageParam = first(params.language);
    if (languageParam) setLanguage(coerceLanguage(languageParam));
    setFromSpark(true);
    setError(null);
  }, [params]);

  // Footage uploaded from Capture > Import arrives as an already-uploaded key.
  useEffect(() => {
    const key = first(params.recording_key).trim();
    if (!key || appliedImportRef.current === key) return;
    appliedImportRef.current = key;
    setFile(null);
    setRecordingKey(key);
    setImportedName(first(params.recording_name).trim() || "Imported footage");
    setError(null);
  }, [params.recording_key, params.recording_name]);

  useEffect(() => {
    let active = true;
    const routeKey = first(params.broll_key).trim();

    if (routeKey) {
      setBrollIntroKey(routeKey);
      void saveAttachedBrollKey(token, routeKey);
      return () => {
        active = false;
      };
    }

    void loadAttachedBrollKey(token).then((savedKey) => {
      if (active && savedKey) setBrollIntroKey(savedKey);
    });
    return () => {
      active = false;
    };
  }, [params.broll_key, token]);

  useEffect(() => {
    let active = true;
    Promise.all([
      listVoices({ token }).catch(() => [] as Voice[]),
      listMyVoices({ token }).catch(() => [] as UserVoice[]),
      listMyWorkspaces({ token }).catch(() => [] as Workspace[]),
    ]).then(([v, mine, ws]) => {
      if (!active) return;
      setVoices(v);
      setMyVoices(mine);
      setWorkspaces(ws);
      // Default to the first catalog voice, else the first cloned voice.
      if (v[0]) setVoiceName(catalogSelector(v[0]));
      else if (mine[0]) setVoiceName(mine[0].voice_id);
      // If the previously-selected charge workspace vanished, fall back to
      // personal so we never send a stale/invalid workspace_id.
      setChargeWorkspaceId((prev) =>
        prev && ws.some((w) => w.id === prev) ? prev : null,
      );
    });
    return () => {
      active = false;
    };
  }, [token]);

  // Avatars are loaded on focus so a just-created custom avatar (from the
  // avatars screen) shows up immediately. The current selection is preserved
  // when it still exists, else it defaults to the first avatar.
  const loadAvatars = useCallback(async () => {
    const list = await listAvatars({ token }).catch(() => [] as Avatar[]);
    setAvatars(list);
    setAvatarId((prev) => {
      if (prev && list.some((a) => avatarSelectId(a) === prev)) return prev;
      return list[0] ? avatarSelectId(list[0]) : null;
    });
  }, [token]);

  useFocusEffect(
    useCallback(() => {
      let active = true;
      void loadAvatars().catch(() => {
        if (active) setAvatars([]);
      });
      void reloadQuote();
      return () => {
        active = false;
      };
    }, [loadAvatars, reloadQuote]),
  );

  const applyTemplate = (template: Template) => {
    setTemplateId(template.id);
    setSubject(template.video_subject);
    setLayout(coerceLayout(template.layout, layout));
    setCaptionStyle(template.caption_style || DEFAULT_CAPTION_STYLE);
    setLanguage(coerceLanguage(template.language));
    if (
      typeof template.target_duration_s === "number" &&
      template.target_duration_s > 0
    ) {
      setDurationS(template.target_duration_s);
    }
    setError(null);
  };

  const upload = async (picked: LocalFile | null) => {
    if (!picked) return;
    setFile(picked);
    setImportedName(null);
    setRecordingKey(null);
    setProgress(0);
    setError(null);
    setPhase("uploading");
    try {
      const { key } = await presignAndUpload(picked, {
        token,
        onProgress: setProgress,
      });
      setRecordingKey(key);
    } catch (err) {
      setError(describe(err));
    } finally {
      setPhase("idle");
    }
  };

  // Resume a saved draft: restore the brief and upload its clip. Only once
  // generation is available (otherwise the waitlist home is shown instead).
  const draftParam = first(params.draft).trim();
  useEffect(() => {
    if (!draftParam || !generationAllowed) return;
    if (appliedDraftRef.current === draftParam) return;
    appliedDraftRef.current = draftParam;
    let active = true;
    void (async () => {
      const draft = await getDraft(draftParam);
      if (!active) return;
      if (!draft) {
        setError("That draft is no longer on this device.");
        return;
      }
      resumedDraftRef.current = draft.id;
      if (draft.subject) setSubject(draft.subject);
      if (draft.captionStyle) setCaptionStyle(draft.captionStyle);
      if (!draft.media) return;
      if (!(await draftMediaAvailable(draft.media))) {
        if (active) {
          setError(
            "This draft's clip is no longer on this device. Pick the recording again below.",
          );
        }
        return;
      }
      if (active) await upload(draft.media);
    })();
    return () => {
      active = false;
    };
    // `upload` is recreated each render; the ref guard makes this run once per draft.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftParam, generationAllowed]);

  const onPickFiles = async () => {
    try {
      await upload(await pickRecordingFromFiles());
    } catch (err) {
      setError(describe(err));
    }
  };

  const onPickLibrary = async () => {
    try {
      await upload(await pickRecordingFromLibrary());
    } catch (err) {
      setError(describe(err));
    }
  };

  // Captions-only is the avatar-less path: captions are burned over the screen
  // recording using its own audio, so NO avatar or voice provider is required.
  // The avatar layouts keep requiring both, exactly as before.
  const captionsOnly = layout === "captions_only";

  // In BYOV mode the uploaded narration stands in for a picked TTS voice, so we
  // require `voiceoverKey` instead of `voiceName`. Captions-only needs neither.
  const voiceReady = captionsOnly
    ? true
    : useOwnVoiceover
      ? !!voiceoverKey
      : !!voiceName;
  const avatarReady = captionsOnly ? true : !!avatarId;

  const canSubmit =
    generationAllowed &&
    !!subject.trim() &&
    !!recordingKey &&
    avatarReady &&
    voiceReady &&
    phase === "idle";

  const briefReady = !!subject.trim() && avatarReady && voiceReady;
  const activeFlowStage: CreatorFlowStage =
    phase === "submitting"
      ? "render"
      : recordingKey
        ? "brief"
        : "footage";
  const completedFlowStages: CreatorFlowStage[] = [
    ...(recordingKey ? (["footage"] as const) : []),
    ...(recordingKey && briefReady ? (["brief"] as const) : []),
  ];

  const onSubmit = async () => {
    if (!generationAllowed) {
      setError(
        capabilityState.error ||
          "Reel generation is not available on this account right now.",
      );
      return;
    }
    if (!recordingKey) return;
    if (!captionsOnly) {
      if (!avatarId) return;
      if (useOwnVoiceover ? !voiceoverKey : !voiceName) return;
    }
    setPhase("submitting");
    setError(null);
    try {
      const request: JobCreateRequest = {
        params: {
          video_subject: subject.trim(),
          ...(script.trim() ? { video_script: script.trim() } : {}),
          // `voice_name` is required by the params shape; in BYOV mode the
          // backend ignores it in favour of `voiceover_key`. Captions-only sends
          // an empty selector — the backend derives narration from the recording.
          voice_name: captionsOnly ? "" : (voiceName ?? ""),
          // Captions-only carries no avatar; the backend skips the avatar stage.
          avatar_id: captionsOnly ? "" : (avatarId ?? ""),
          avatar_provider: "heygen",
          caption_style: captionStyle,
          layout,
          aspect: "9:16",
          language,
          target_duration_s: durationS,
          platforms: [],
          screen_recording_key: recordingKey,
          ...(!captionsOnly && useOwnVoiceover && voiceoverKey
            ? { voiceover_key: voiceoverKey }
            : {}),
        },
        ...(!captionsOnly && avatarId ? { avatar_id: avatarId } : {}),
        // Only send a TTS narrator selector when NOT bringing your own voiceover
        // and NOT in captions-only mode.
        ...(!captionsOnly && !useOwnVoiceover && voiceName
          ? { voice_id: providerVoiceId(voiceName) }
          : {}),
        variants,
        caption_style: captionStyle,
        ...(musicId ? { music_id: musicId } : {}),
        ...(musicPrompt && musicPrompt.trim()
          ? {
              music_prompt: musicPrompt.trim(),
              ...(bgmProvider ? { bgm_provider: bgmProvider } : {}),
            }
          : {}),
        ...(chargeWorkspaceId ? { workspace_id: chargeWorkspaceId } : {}),
        ...(autoTighten ? { auto_tighten: true } : {}),
        ...(autoZoom ? { auto_zoom: true } : {}),
        ...(cameraMotion !== "none" ? { camera_motion: cameraMotion } : {}),
        ...(removeBg ? { remove_bg: true } : {}),
        ...(brollIntroKey ? { broll_intro_key: brollIntroKey } : {}),
      };
      const fingerprint = JSON.stringify(request);
      if (pendingCreateRef.current?.fingerprint !== fingerprint) {
        pendingCreateRef.current = {
          fingerprint,
          idempotencyKey: createIdempotencyKey(),
        };
      }
      const result = await createJob(request, {
        token,
        idempotencyKey: pendingCreateRef.current.idempotencyKey,
      });
      pendingCreateRef.current = undefined;
      if (resumedDraftRef.current) {
        // The draft is now a real job; drop the local copy and its clip.
        const draftId = resumedDraftRef.current;
        resumedDraftRef.current = null;
        await discardDraft(draftId).catch(() => undefined);
      }
      await saveAttachedBrollKey(token, null);
      setBrollIntroKey(null);
      // A multi-variant create returns a shared `batch_id`; route to the batch
      // progress screen so every variant is watched together. A single job (no
      // batch_id) routes to its own detail as before.
      if (result.batch_id) {
        router.push(`/jobs/reels/batch/${result.batch_id}`);
      } else {
        const firstId = result.job_ids?.[0] ?? result.job_id;
        router.push(`/job/${firstId}`);
      }
    } catch (err) {
      setError(describe(err));
      setPhase("idle");
    }
  };

  if (capabilityState.loading) {
    return (
      <View style={[styles.container, styles.centered]}>
        <ActivityIndicator color={colors.accent} />
        <Text style={styles.meta}>Checking reel generation availability…</Text>
      </View>
    );
  }

  // When generation is not enabled for this account, never dead-end: show the
  // honest, useful waitlist-era home (join the waitlist, preview caption looks,
  // record a clip for later) instead of a bare terminal message.
  if (!generationAllowed) {
    return <WaitlistHome token={token} source="mobile-create" />;
  }

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
    >
      <CreatorFlowRail
        active={activeFlowStage}
        completed={completedFlowStages}
      />

      {fromSpark ? (
        <View style={styles.sparkBanner}>
          <Text style={styles.sparkBannerText}>
            Prefilled from a Spark idea — attach a screen recording to finish.
          </Text>
        </View>
      ) : null}

      <View style={styles.sectionHeadRow}>
        <Text style={styles.h2}>Start from a template</Text>
        <Pressable onPress={() => router.push("/catalog/templates")}>
          <Text style={styles.browseLink}>Browse all</Text>
        </Pressable>
      </View>
      <TemplatesRow value={templateId} onApply={applyTemplate} token={token} />

      <Text style={styles.h2}>1 · Screen recording</Text>
      <View style={styles.row}>
        <Pressable
          style={styles.secondary}
          onPress={onPickFiles}
          disabled={phase !== "idle"}
        >
          <Text style={styles.secondaryText}>Browse files</Text>
        </Pressable>
        <Pressable
          style={styles.secondary}
          onPress={onPickLibrary}
          disabled={phase !== "idle"}
        >
          <Text style={styles.secondaryText}>From library</Text>
        </Pressable>
      </View>

      {file ? (
        <View style={styles.footageCard}>
          <JobVideo key={file.uri} uri={file.uri} isMuted />
          <View style={styles.fileCard}>
            <Text style={styles.fileName} numberOfLines={1}>
              {file.name}
            </Text>
            <Text style={styles.meta}>
              {file.mimeType} · {(file.size / (1024 * 1024)).toFixed(1)} MB
            </Text>
            {phase === "uploading" ? (
              <View style={styles.progressRow}>
                <View style={styles.progressTrack}>
                  <View
                    style={[
                      styles.progressFill,
                      { width: `${Math.round(progress * 100)}%` },
                    ]}
                  />
                </View>
                <Text style={styles.meta}>{Math.round(progress * 100)}%</Text>
              </View>
            ) : recordingKey ? (
              <Text style={styles.uploaded}>Footage uploaded</Text>
            ) : (
              <Pressable
                style={styles.retryUpload}
                onPress={() => void upload(file)}
                accessibilityRole="button"
                accessibilityLabel="Retry footage upload"
              >
                <Text style={styles.retryUploadText}>Retry upload</Text>
              </Pressable>
            )}
          </View>
        </View>
      ) : recordingKey && importedName ? (
        <View style={styles.fileCard}>
          <Text style={styles.fileName} numberOfLines={1}>
            {importedName}
          </Text>
          <Text style={styles.uploaded}>Footage uploaded</Text>
        </View>
      ) : null}

      <Text style={styles.h2}>2 · Subject</Text>
      <View style={styles.row}>
        {brollAvailable ? (
          <Pressable
            style={styles.secondary}
            onPress={() => router.push("/(tabs)/broll")}
          >
            <Text style={styles.secondaryText}>
              {brollIntroKey ? "Change AI B-roll" : "Generate AI B-roll"}
            </Text>
          </Pressable>
        ) : null}
        {brollIntroKey ? (
          <Pressable
            style={styles.secondary}
            onPress={() => {
              setBrollIntroKey(null);
              void saveAttachedBrollKey(token, null);
            }}
          >
            <Text style={styles.secondaryText}>Remove attachment</Text>
          </Pressable>
        ) : null}
      </View>
      {brollIntroKey ? (
        <Text style={styles.uploaded}>AI B-roll attached</Text>
      ) : null}
      <TextInput
        style={styles.input}
        value={subject}
        onChangeText={setSubject}
        placeholder="What is this reel about?"
        placeholderTextColor={colors.textFaint}
        multiline
      />

      {script ? (
        <>
          <Text style={styles.h3}>Script (from Spark)</Text>
          <TextInput
            style={styles.input}
            value={script}
            onChangeText={setScript}
            placeholder="Narration script beats"
            placeholderTextColor={colors.textFaint}
            multiline
          />
        </>
      ) : null}

      {captionsOnly ? (
        <View style={styles.sparkBanner}>
          <Text style={styles.sparkBannerText}>
            Captions-only reel — your screen recording is captioned with its own
            audio. No avatar or voice needed.
          </Text>
        </View>
      ) : (
        <>
          <View style={styles.sectionHeadRow}>
            <Text style={styles.h2}>3 · Avatar</Text>
            <Pressable onPress={() => router.push("/studio/avatars")}>
              <Text style={styles.browseLink}>Avatar gallery</Text>
            </Pressable>
          </View>
          <AvatarPicker
            avatars={avatars}
            selected={avatarId}
            onSelect={setAvatarId}
          />

          <View style={styles.sectionHeadRow}>
            <Text style={styles.h2}>4 · Voice</Text>
            <Pressable onPress={() => router.push("/studio/voices")}>
              <Text style={styles.browseLink}>Voice library</Text>
            </Pressable>
          </View>
          <View style={styles.toggleRow}>
            <Switch
              value={useOwnVoiceover}
              onValueChange={(next) => {
                setUseOwnVoiceover(next);
                setError(null);
              }}
              disabled={phase !== "idle"}
              trackColor={{ false: colors.border, true: colors.accent }}
              thumbColor={colors.textPrimary}
            />
            <Text style={styles.toggleText}>Use my own voiceover</Text>
          </View>

          {useOwnVoiceover ? (
            <VoiceoverPicker
              token={token}
              voiceoverKey={voiceoverKey}
              onUploaded={setVoiceoverKey}
              disabled={phase !== "idle"}
            />
          ) : (
            <>
              <Chips
                items={voices.map((v) => ({
                  id: catalogSelector(v),
                  label: v.name || v.voice_id,
                }))}
                selected={voiceName}
                onSelect={setVoiceName}
                emptyText="No voices available."
              />

              {myVoices.length > 0 ? (
                <>
                  <Text style={styles.h3}>Your voices</Text>
                  <Chips
                    items={myVoices.map((v) => ({
                      id: v.voice_id,
                      label: v.name || v.voice_id,
                    }))}
                    selected={voiceName}
                    onSelect={setVoiceName}
                  />
                </>
              ) : null}
            </>
          )}
        </>
      )}

      <View style={styles.sectionHeadRow}>
        <Text style={styles.h2}>5 · Layout</Text>
        <Pressable onPress={() => router.push("/catalog/layouts")}>
          <Text style={styles.browseLink}>Browse all</Text>
        </Pressable>
      </View>
      <Chips
        items={LAYOUTS.map((l) => ({ id: l, label: l }))}
        selected={layout}
        onSelect={(id) => setLayout(id as Layout)}
      />

      <Text style={styles.h2}>6 · Language</Text>
      <Chips
        items={LANGUAGES.map((l) => ({ id: l, label: l }))}
        selected={language}
        onSelect={(id) => setLanguage(id as Language)}
      />

      <View style={styles.sectionHeadRow}>
        <Text style={styles.h2}>7 · Caption style</Text>
        <Pressable onPress={() => router.push("/catalog/caption-styles")}>
          <Text style={styles.browseLink}>Browse all</Text>
        </Pressable>
      </View>
      <CaptionStylePicker
        value={captionStyle}
        onSelect={setCaptionStyle}
        token={token}
      />

      <View style={styles.sectionHeadRow}>
        <Text style={styles.h2}>8 · Background music</Text>
        <Pressable onPress={() => router.push("/catalog/music")}>
          <Text style={styles.browseLink}>Music library</Text>
        </Pressable>
      </View>
      <MusicPicker
        value={musicId}
        onSelect={setMusicId}
        prompt={musicPrompt}
        provider={bgmProvider}
        onSelectPrompt={(nextPrompt, nextProvider) => {
          setMusicPrompt(nextPrompt);
          setBgmProvider(nextProvider);
        }}
        token={token}
      />

      <Text style={styles.h2}>9 · Variations</Text>
      <VariantsStepper
        value={variants}
        onChange={setVariants}
        disabled={phase !== "idle"}
      />

      {workspaces.length > 0 ? (
        <>
          <Text style={styles.h2}>10 · Charge to</Text>
          <WorkspaceSelect
            workspaces={workspaces}
            value={chargeWorkspaceId}
            onSelect={setChargeWorkspaceId}
            disabled={phase !== "idle"}
          />
          <Text style={styles.meta}>
            {chargeWorkspaceId
              ? "Charges this workspace's shared credit pool."
              : "Charges your personal credits."}
          </Text>
        </>
      ) : null}

      <Text style={styles.h2}>11 · Retention</Text>
      <View style={styles.toggleRow}>
        <Switch
          value={autoTighten}
          onValueChange={setAutoTighten}
          disabled={phase !== "idle"}
          trackColor={{ false: colors.border, true: colors.accent }}
          thumbColor={colors.textPrimary}
        />
        <Text style={styles.toggleText}>
          Auto-tighten (remove silent/dead gaps)
        </Text>
      </View>
      <Text style={styles.meta}>
        Pre-trims silent and static stretches from your screen recording before
        editing. Your voiceover and captions stay untouched.
      </Text>

      <Text style={styles.h2}>12 · Editing polish</Text>
      <View style={styles.toggleRow}>
        <Switch
          value={autoZoom}
          onValueChange={setAutoZoom}
          disabled={phase !== "idle"}
          trackColor={{ false: colors.border, true: colors.accent }}
          thumbColor={colors.textPrimary}
        />
        <Text style={styles.toggleText}>
          Auto-zoom (scene-driven punch-in)
        </Text>
      </View>

      <Text style={styles.h3}>Camera motion</Text>
      <Chips
        items={CAMERA_MOTIONS.map((m) => ({
          id: m,
          label: CAMERA_MOTION_LABELS[m],
        }))}
        selected={cameraMotion}
        onSelect={(id) => setCameraMotion(id as CameraMotion)}
      />

      <View style={styles.toggleRow}>
        <Switch
          value={removeBg}
          onValueChange={setRemoveBg}
          disabled={phase !== "idle"}
          trackColor={{ false: colors.border, true: colors.accent }}
          thumbColor={colors.textPrimary}
        />
        <Text style={styles.toggleText}>Remove avatar background</Text>
      </View>
      <Text style={styles.meta}>
        Optional cinematic passes applied to your screen recording before
        editing. Each is duration-preserving, so your voiceover and captions stay
        untouched.
      </Text>

      {isRouteAvailable("/catalog/quote") ? (
      <>
      <View style={styles.sectionHeadRow}>
        <Text style={styles.h2}>Estimate cost</Text>
        <Pressable onPress={() => router.push("/catalog/quote")}>
          <Text style={styles.browseLink}>Open estimator</Text>
        </Pressable>
      </View>
      {lastQuote ? (
        <Pressable
          style={styles.estimateCard}
          onPress={() => router.push("/catalog/quote")}
          accessibilityRole="button"
        >
          <View style={styles.estimateInfo}>
            <Text style={styles.estimateTotal}>
              {formatUsdMicros(lastQuote.total_micros)}
            </Text>
            <Text style={styles.meta}>
              {lastQuote.stages.length} stage{lastQuote.stages.length === 1 ? "" : "s"}
              {lastQuote.within_budget ? "" : " · over budget"}
            </Text>
          </View>
          <Text style={styles.browseLink}>Review</Text>
        </Pressable>
      ) : (
        <Text style={styles.meta}>
          Compare models and preview the pay-as-you-go cost of your choices before you create.
        </Text>
      )}
      </>
      ) : null}

      <GenerationErrorNotice message={error} style={styles.error} />

      <Pressable
        style={[styles.primary, !canSubmit && styles.disabled]}
        onPress={onSubmit}
        disabled={!canSubmit}
      >
        {phase === "submitting" ? (
          <ActivityIndicator color={colors.onAccent} />
        ) : (
          <Text style={styles.primaryText}>
            {variants > 1 ? `Create ${variants} reels` : "Create reel"}
          </Text>
        )}
      </Pressable>
      <View style={{ height: 40 }} />
    </ScrollView>
  );
}

function createIdempotencyKey(): string {
  return `mobile-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

interface ChipItem {
  id: string;
  label: string;
}

function Chips({
  items,
  selected,
  onSelect,
  emptyText,
}: {
  items: ChipItem[];
  selected: string | null;
  onSelect: (id: string) => void;
  emptyText?: string;
}) {
  if (items.length === 0) {
    return <Text style={styles.meta}>{emptyText ?? "Nothing to show."}</Text>;
  }
  return (
    <View style={styles.chips}>
      {items.map((item) => {
        const active = item.id === selected;
        return (
          <Pressable
            key={item.id}
            style={[styles.chip, active && styles.chipActive]}
            onPress={() => onSelect(item.id)}
          >
            <Text style={[styles.chipText, active && styles.chipTextActive]}>
              {item.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

function describe(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Something went wrong.";
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  centered: {
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
    gap: 12,
  },
  content: { padding: 20, gap: 10 },
  h2: { color: colors.textPrimary, fontSize: 16, fontWeight: "700", marginTop: 12 },
  sectionHeadRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  browseLink: { color: colors.accent, fontSize: 13, fontWeight: "700", marginTop: 12 },
  h3: { color: colors.textSecondary, fontSize: 13, fontWeight: "600", marginTop: 6 },
  row: { flexDirection: "row", gap: 10 },
  secondary: {
    flex: 1,
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
  },
  secondaryText: { color: colors.textSecondary, fontWeight: "600" },
  fileCard: {
    backgroundColor: colors.surface,
    padding: 14,
    gap: 8,
  },
  footageCard: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 14,
    overflow: "hidden",
  },
  fileName: { color: colors.textPrimary, fontWeight: "600" },
  progressRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  progressTrack: {
    flex: 1,
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.border,
    overflow: "hidden",
  },
  progressFill: { height: 6, backgroundColor: colors.accent },
  uploaded: { color: colors.success, fontWeight: "600" },
  retryUpload: {
    alignSelf: "flex-start",
    borderColor: colors.accent,
    borderWidth: 1,
    borderRadius: 9,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  retryUploadText: { color: colors.accent, fontSize: 13, fontWeight: "700" },
  input: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    color: colors.textPrimary,
    fontSize: 16,
    paddingHorizontal: 14,
    paddingVertical: 12,
    minHeight: 60,
    textAlignVertical: "top",
  },
  toggleRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  toggleText: { color: colors.textSecondary, fontSize: 14, fontWeight: "600" },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  chipActive: { backgroundColor: colors.accent, borderColor: colors.accent },
  chipText: { color: colors.textSecondary },
  chipTextActive: { color: colors.onAccent, fontWeight: "700" },
  meta: { color: colors.textFaint, fontSize: 13 },
  estimateCard: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
  },
  estimateInfo: { gap: 2 },
  estimateTotal: { color: colors.textPrimary, fontSize: 18, fontWeight: "800" },
  error: { color: colors.danger, fontSize: 14, marginTop: 8 },
  primary: {
    backgroundColor: colors.accent,
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: "center",
    marginTop: 16,
  },
  disabled: { opacity: 0.5 },
  primaryText: { color: colors.onAccent, fontSize: 16, fontWeight: "700" },
  sparkBanner: {
    backgroundColor: colors.surfaceAlt,
    borderColor: colors.accent,
    borderWidth: 1,
    borderRadius: 10,
    padding: 12,
  },
  sparkBannerText: { color: colors.textSecondary, fontSize: 13, lineHeight: 18 },
});
