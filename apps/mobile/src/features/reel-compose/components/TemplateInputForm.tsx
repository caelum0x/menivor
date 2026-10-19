import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { useRouter } from "expo-router";

import {
  getTemplate,
  instantiateTemplate,
  type TemplateDetail,
  type TemplateInputDef,
} from "@/lib/templates";
import {
  ApiError,
  createJob,
  isAbortError,
  listAvatars,
  listVoices,
  presignAndUpload,
  type LocalFile,
} from "@/lib/api";
import {
  avatarSelectId,
  avatarLabel,
  type Avatar,
  type Job,
  type Voice,
} from "@/lib/types";
import {
  pickRecordingFromFiles,
  pickRecordingFromLibrary,
} from "@/src/shared/media";
import {
  buildJobRequest,
  createIdempotencyKey,
  defaultInputValues,
  missingRequiredInputs,
} from "../logic";
import { GenerationErrorNotice } from "@/components/billing/GenerationErrorNotice";

interface TemplateInputFormProps {
  token: string | undefined;
  slug: string;
  /** Server-owned reel generation gate (from useGenerationCapabilities). */
  generationAllowed: boolean;
  /** Message to surface when generation is gated off. */
  capabilityError: string;
  source?: { kind: "trend"; id: string; label?: string; forecastId?: string };
  /** Called with the freshly created job to advance to review. */
  onGenerated: (job: Job) => void;
  onBack: () => void;
}

type Phase = "idle" | "uploading" | "submitting";

function describe(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Something went wrong.";
}

function clampDuration(value: number, detail: TemplateDetail): number {
  if (!Number.isFinite(value)) return detail.default_duration_s;
  return Math.max(detail.min_duration_s, Math.min(detail.max_duration_s, value));
}

/**
 * Collect a template's creator inputs + the avatar/voice/screen-recording the
 * pipeline needs, then instantiate the template into a reel draft and submit it
 * as a real job. Instantiation always runs; the job create is gated by the
 * server-owned generation capability.
 */
export function TemplateInputForm({
  token,
  slug,
  generationAllowed,
  capabilityError,
  source,
  onGenerated,
  onBack,
}: TemplateInputFormProps) {
  const router = useRouter();
  const [detail, setDetail] = useState<TemplateDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [catalogNonce, setCatalogNonce] = useState(0);
  const [avatarCatalogError, setAvatarCatalogError] = useState<string | null>(null);
  const [voiceCatalogError, setVoiceCatalogError] = useState<string | null>(null);

  const [values, setValues] = useState<Record<string, string>>({});
  const [durationS, setDurationS] = useState<number>(0);
  const [avatars, setAvatars] = useState<Avatar[]>([]);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [avatarId, setAvatarId] = useState<string | null>(null);
  const [voiceId, setVoiceId] = useState<string | null>(null);

  const [file, setFile] = useState<LocalFile | null>(null);
  const [recordingKey, setRecordingKey] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const pendingCreateRef = useRef<
    { fingerprint: string; idempotencyKey: string } | undefined
  >(undefined);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setLoading(true);
    setLoadError(null);
    void getTemplate(slug, { token, signal: controller.signal })
      .then((tmpl) => {
        if (!active) return;
        setDetail(tmpl);
        setValues(defaultInputValues(tmpl.inputs));
        setDurationS(tmpl.default_duration_s);
      })
      .catch((err: unknown) => {
        if (!active || isAbortError(err)) return;
        setLoadError(describe(err));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [slug, token]);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setCatalogLoading(true);
    setAvatarCatalogError(null);
    setVoiceCatalogError(null);
    Promise.all([
      listAvatars({ token, signal: controller.signal })
        .then((items) => ({ items, error: null as string | null }))
        .catch((err: unknown) => {
          if (isAbortError(err)) throw err;
          return { items: [] as Avatar[], error: describe(err) };
        }),
      listVoices({ token, signal: controller.signal })
        .then((items) => ({ items, error: null as string | null }))
        .catch((err: unknown) => {
          if (isAbortError(err)) throw err;
          return { items: [] as Voice[], error: describe(err) };
        }),
    ])
      .then(([avatarCatalog, voiceCatalog]) => {
        if (!active) return;
        const avatarList = avatarCatalog.items;
        const voiceList = voiceCatalog.items;
        setAvatars(avatarList);
        setVoices(voiceList);
        setAvatarCatalogError(avatarCatalog.error);
        setVoiceCatalogError(voiceCatalog.error);
        setAvatarId(
          avatarList.map(avatarSelectId).find((id) => id.length > 0) ?? null,
        );
        setVoiceId(
          voiceList.map((voice) => voice.voice_id.trim()).find(Boolean) ?? null,
        );
      })
      .catch((err: unknown) => {
        if (!active || isAbortError(err)) return;
        const message = describe(err);
        setAvatarCatalogError(message);
        setVoiceCatalogError(message);
      })
      .finally(() => {
        if (active) setCatalogLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [catalogNonce, token]);

  const setValue = useCallback((key: string, next: string) => {
    setValues((prev) => ({ ...prev, [key]: next }));
    setError(null);
  }, []);

  const upload = useCallback(
    async (picked: LocalFile | null): Promise<void> => {
      if (!picked) return;
      setFile(picked);
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
    },
    [token],
  );

  const onPickFiles = useCallback(async () => {
    try {
      await upload(await pickRecordingFromFiles());
    } catch (err) {
      setError(describe(err));
    }
  }, [upload]);

  const onPickLibrary = useCallback(async () => {
    try {
      await upload(await pickRecordingFromLibrary());
    } catch (err) {
      setError(describe(err));
    }
  }, [upload]);

  if (loading || catalogLoading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator color="#E6C76A" />
        <Text style={styles.meta}>Loading template and creator catalogs…</Text>
      </View>
    );
  }

  if (loadError || !detail) {
    return (
      <View style={styles.centered}>
        <View style={styles.errorBanner}>
          <Text style={styles.errorText}>
            {loadError ?? "Template unavailable."}
          </Text>
        </View>
        <Pressable style={styles.secondary} onPress={onBack}>
          <Text style={styles.secondaryText}>Back to templates</Text>
        </Pressable>
      </View>
    );
  }

  const missing = missingRequiredInputs(detail.inputs, values);
  const avatarOptions = avatars
    .map((avatar) => ({
      id: avatarSelectId(avatar),
      label: avatarLabel(avatar),
    }))
    .filter((item) => item.id.length > 0);
  const voiceOptions = voices
    .map((voice) => ({
      id: voice.voice_id.trim(),
      label: voice.name || voice.voice_id,
    }))
    .filter((item) => item.id.length > 0);
  const catalogsReady =
    !avatarCatalogError &&
    !voiceCatalogError &&
    avatarOptions.length > 0 &&
    voiceOptions.length > 0;
  const canSubmit =
    generationAllowed &&
    catalogsReady &&
    missing.length === 0 &&
    !!recordingKey &&
    !!avatarId &&
    !!voiceId &&
    phase === "idle";

  const onGenerate = async (): Promise<void> => {
    if (!generationAllowed) {
      setError(
        capabilityError ||
          "Reel generation is not available on this account right now.",
      );
      return;
    }
    if (avatarCatalogError || voiceCatalogError) {
      setError("Avatar and voice catalogs must be available before generation.");
      return;
    }
    if (avatarOptions.length === 0 || voiceOptions.length === 0) {
      setError("Add an avatar and voice before generation.");
      return;
    }
    if (!recordingKey || !avatarId || !voiceId) {
      setError("Upload footage and select an avatar and voice before generation.");
      return;
    }
    if (missing.length > 0) {
      setError("Fill in every required field first.");
      return;
    }
    setPhase("submitting");
    setError(null);
    try {
      // 1) Template + inputs → pipeline-ready reel draft.
      const instantiated = await instantiateTemplate(
        slug,
        { inputs: values, duration_s: durationS },
        { token },
      );
      // 2) Draft + creator selections → a real job create request.
      const jobRequest = buildJobRequest({
        draft: instantiated.reel_draft,
        avatarId,
        voiceId,
        recordingKey,
        durationS,
        source,
      });
      const fingerprint = JSON.stringify(jobRequest);
      if (pendingCreateRef.current?.fingerprint !== fingerprint) {
        pendingCreateRef.current = {
          fingerprint,
          idempotencyKey: createIdempotencyKey(),
        };
      }
      const created = await createJob(jobRequest, {
        token,
        idempotencyKey: pendingCreateRef.current.idempotencyKey,
      });
      pendingCreateRef.current = undefined;
      onGenerated(created);
    } catch (err) {
      setError(describe(err));
      setPhase("idle");
    }
  };

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
    >
      <Pressable onPress={onBack} style={styles.backRow}>
        <Text style={styles.backText}>Back to templates</Text>
      </Pressable>

      <Text style={styles.title}>{detail.name}</Text>
      <Text style={styles.desc}>{detail.description}</Text>
      {source ? (
        <View style={styles.sourceBanner}>
          <Text style={styles.sourceEyebrow}>BUILDING FROM TREND</Text>
          <Text style={styles.sourceLabel}>{source.label || source.id}</Text>
          {source.forecastId ? (
            <Text style={styles.sourceForecast}>
              Forecast {source.forecastId}
            </Text>
          ) : null}
        </View>
      ) : null}

      <Text style={styles.h2}>Inputs</Text>
      {detail.inputs.length === 0 ? (
        <Text style={styles.meta}>This template needs no extra inputs.</Text>
      ) : (
        detail.inputs.map((input) => (
          <InputField
            key={input.key}
            input={input}
            value={values[input.key] ?? ""}
            invalid={missing.includes(input.key)}
            onChange={(next) => setValue(input.key, next)}
          />
        ))
      )}

      <Text style={styles.h2}>
        Duration ({detail.min_duration_s}–{detail.max_duration_s}s)
      </Text>
      <TextInput
        style={styles.input}
        value={String(durationS)}
        onChangeText={(text) => {
          const parsed = Number.parseInt(text.replace(/[^0-9]/g, ""), 10);
          setDurationS(Number.isNaN(parsed) ? 0 : parsed);
        }}
        onBlur={() => setDurationS((d) => clampDuration(d, detail))}
        keyboardType="number-pad"
        placeholderTextColor="#6f6c65"
      />

      <Text style={styles.h2}>Screen recording</Text>
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
        <View style={styles.fileCard}>
          <Text style={styles.fileName} numberOfLines={1}>
            {file.name}
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
            <Text style={styles.uploaded}>Uploaded</Text>
          ) : null}
        </View>
      ) : (
        <Text style={styles.meta}>
          Attach the screen capture this reel narrates over.
        </Text>
      )}

      <Text style={styles.h2}>Avatar</Text>
      {avatarCatalogError ? (
        <CatalogNotice
          title="Avatar catalog unavailable"
          message={avatarCatalogError}
          actionLabel="Retry catalogs"
          onAction={() => setCatalogNonce((value) => value + 1)}
        />
      ) : avatarOptions.length === 0 ? (
        <CatalogNotice
          title="No avatars available"
          message="Create an avatar, then refresh this form before generating."
          actionLabel="Create avatar"
          onAction={() => router.push("/account/avatars")}
          secondaryLabel="Refresh"
          onSecondary={() => setCatalogNonce((value) => value + 1)}
        />
      ) : (
        <Chips
          items={avatarOptions}
          selected={avatarId}
          onSelect={setAvatarId}
        />
      )}

      <Text style={styles.h2}>Voice</Text>
      {voiceCatalogError ? (
        <CatalogNotice
          title="Voice catalog unavailable"
          message={voiceCatalogError}
          actionLabel="Retry catalogs"
          onAction={() => setCatalogNonce((value) => value + 1)}
        />
      ) : voiceOptions.length === 0 ? (
        <CatalogNotice
          title="No voices available"
          message="Add a narrator, then refresh this form before generating."
          actionLabel="Manage voices"
          onAction={() => router.push("/account/voices")}
          secondaryLabel="Refresh"
          onSecondary={() => setCatalogNonce((value) => value + 1)}
        />
      ) : (
        <Chips
          items={voiceOptions}
          selected={voiceId}
          onSelect={setVoiceId}
        />
      )}

      {!generationAllowed ? (
        <Text style={styles.gate}>
          {capabilityError ||
            "Reel generation is not available on this account right now."}
        </Text>
      ) : null}

      <GenerationErrorNotice message={error} style={styles.error} />

      <Pressable
        style={[styles.primary, !canSubmit && styles.disabled]}
        onPress={onGenerate}
        disabled={!canSubmit}
      >
        {phase === "submitting" ? (
          <ActivityIndicator color="#0f0f10" />
        ) : (
          <Text style={styles.primaryText}>Generate reel</Text>
        )}
      </Pressable>
      <View style={{ height: 40 }} />
    </ScrollView>
  );
}

interface InputFieldProps {
  input: TemplateInputDef;
  value: string;
  invalid: boolean;
  onChange: (next: string) => void;
}

function InputField({ input, value, invalid, onChange }: InputFieldProps) {
  return (
    <View style={styles.field}>
      <Text style={styles.label}>
        {input.label}
        {input.required ? <Text style={styles.required}> *</Text> : null}
      </Text>
      {input.help ? <Text style={styles.help}>{input.help}</Text> : null}
      {input.choices.length > 0 ? (
        <Chips
          items={input.choices.map((c) => ({ id: c, label: c }))}
          selected={value || null}
          onSelect={onChange}
        />
      ) : (
        <TextInput
          style={[styles.input, invalid && styles.inputInvalid]}
          value={value}
          onChangeText={onChange}
          placeholder={input.label}
          placeholderTextColor="#6f6c65"
          multiline
        />
      )}
    </View>
  );
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

function CatalogNotice({
  title,
  message,
  actionLabel,
  onAction,
  secondaryLabel,
  onSecondary,
}: {
  title: string;
  message: string;
  actionLabel: string;
  onAction: () => void;
  secondaryLabel?: string;
  onSecondary?: () => void;
}) {
  return (
    <View style={styles.catalogNotice}>
      <Text style={styles.catalogTitle}>{title}</Text>
      <Text style={styles.catalogMessage}>{message}</Text>
      <View style={styles.catalogActions}>
        <Pressable style={styles.catalogAction} onPress={onAction}>
          <Text style={styles.catalogActionText}>{actionLabel}</Text>
        </Pressable>
        {secondaryLabel && onSecondary ? (
          <Pressable style={styles.catalogSecondary} onPress={onSecondary}>
            <Text style={styles.catalogSecondaryText}>{secondaryLabel}</Text>
          </Pressable>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0a0a0b" },
  content: { padding: 20, gap: 8 },
  centered: {
    flex: 1,
    backgroundColor: "#0a0a0b",
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
    gap: 12,
  },
  backRow: { paddingVertical: 4 },
  backText: { color: "#E6C76A", fontSize: 14, fontWeight: "600" },
  title: { color: "#ece9e1", fontSize: 22, fontWeight: "800", marginTop: 4 },
  desc: { color: "#ece9e1", fontSize: 14, marginBottom: 4 },
  sourceBanner: {
    borderColor: "#E6C76A",
    borderWidth: 1,
    borderRadius: 10,
    padding: 12,
    marginTop: 8,
    gap: 4,
  },
  sourceEyebrow: {
    color: "#E6C76A",
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 1.1,
  },
  sourceLabel: { color: "#ece9e1", fontSize: 15, fontWeight: "700" },
  sourceForecast: { color: "#ece9e1", fontSize: 11 },
  h2: { color: "#ece9e1", fontSize: 16, fontWeight: "700", marginTop: 14 },
  field: { gap: 4, marginTop: 6 },
  label: { color: "#e6e6ef", fontSize: 14, fontWeight: "600" },
  required: { color: "#E0847F" },
  help: { color: "#6f6c65", fontSize: 12 },
  row: { flexDirection: "row", gap: 10 },
  secondary: {
    flex: 1,
    backgroundColor: "#0f0f10",
    borderColor: "#27272a",
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 12,
    paddingHorizontal: 16,
    alignItems: "center",
  },
  secondaryText: { color: "#ece9e1", fontWeight: "600" },
  input: {
    backgroundColor: "#0f0f10",
    borderColor: "#27272a",
    borderWidth: 1,
    borderRadius: 10,
    color: "#ece9e1",
    fontSize: 16,
    paddingHorizontal: 14,
    paddingVertical: 12,
    minHeight: 48,
    textAlignVertical: "top",
  },
  inputInvalid: { borderColor: "#E0847F" },
  fileCard: {
    backgroundColor: "#0f0f10",
    borderRadius: 10,
    padding: 14,
    gap: 8,
  },
  fileName: { color: "#ece9e1", fontWeight: "600" },
  progressRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  progressTrack: {
    flex: 1,
    height: 6,
    borderRadius: 3,
    backgroundColor: "#27272a",
    overflow: "hidden",
  },
  progressFill: { height: 6, backgroundColor: "#E6C76A" },
  uploaded: { color: "#7CC39B", fontWeight: "600" },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    backgroundColor: "#0f0f10",
    borderColor: "#27272a",
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  chipActive: { backgroundColor: "#E6C76A", borderColor: "#E6C76A" },
  chipText: { color: "#ece9e1" },
  chipTextActive: { color: "#0f0f10", fontWeight: "700" },
  catalogNotice: {
    backgroundColor: "#0b0c0a",
    borderColor: "#E6C76A",
    borderWidth: 1,
    padding: 12,
    gap: 7,
  },
  catalogTitle: {
    color: "#E6C76A",
    fontFamily: "monospace",
    fontSize: 13,
    fontWeight: "700",
  },
  catalogMessage: {
    color: "#ece9e1",
    fontFamily: "monospace",
    fontSize: 12,
    lineHeight: 17,
  },
  catalogActions: { flexDirection: "row", gap: 8, marginTop: 2 },
  catalogAction: {
    backgroundColor: "#E6C76A",
    borderColor: "#E6C76A",
    borderWidth: 1,
    paddingHorizontal: 12,
    paddingVertical: 9,
  },
  catalogActionText: {
    color: "#0b0c0a",
    fontFamily: "monospace",
    fontWeight: "700",
  },
  catalogSecondary: {
    borderColor: "#E6C76A",
    borderWidth: 1,
    paddingHorizontal: 12,
    paddingVertical: 9,
  },
  catalogSecondaryText: {
    color: "#E6C76A",
    fontFamily: "monospace",
    fontWeight: "700",
  },
  meta: { color: "#6f6c65", fontSize: 13 },
  gate: { color: "#f5c451", fontSize: 13, marginTop: 10 },
  error: { color: "#E0847F", fontSize: 14, marginTop: 8 },
  errorBanner: {
    backgroundColor: "#2a1420",
    borderColor: "#E0847F",
    borderWidth: 1,
    borderRadius: 10,
    padding: 12,
  },
  errorText: { color: "#E0847F", fontSize: 14 },
  primary: {
    backgroundColor: "#E6C76A",
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: "center",
    marginTop: 16,
  },
  disabled: { opacity: 0.5 },
  primaryText: { color: "#0f0f10", fontSize: 16, fontWeight: "700" },
});
