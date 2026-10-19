import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Linking,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { JobVideo } from "@/src/shared/media";
import {
  captureSelfie,
  pickSelfieFromLibrary,
  pickVoiceSampleFromFiles,
} from "@/src/shared/media";
import { useSession } from "@/src/shared/auth";
import { pollUntilTerminal } from "@/src/shared/lifecycle";
import {
  ApiError,
  getJob,
  isAbortError,
  presignAndUpload,
} from "@/lib/api";
import { listCharacters, type Character } from "@/lib/characters";
import {
  addCharacterReference,
  getCharacter,
  listCharacterReferences,
  trainCharacter,
  type CharacterDetail,
  type CharacterReference,
} from "@/lib/character-identity";
import {
  generateSpeak,
  getSpeakGeneration,
  listSpeakProviders,
  type SpeakGeneration,
  type SpeakProvider,
} from "@/lib/speak";
import { JobState, isTerminalState } from "@/lib/types";
import { GenerationErrorNotice } from "@/components/billing/GenerationErrorNotice";

function describe(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "Something went wrong.";
}

function progressPercent(progress: number): number {
  return Math.round(Math.max(0, Math.min(100, progress)));
}

function newIdempotencyKey(prefix: string): string {
  return `mobile-${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/** A local, non-persisted view of the in-flight LoRA training job. */
interface TrainingState {
  jobId: string;
  state: number;
  progress: number;
  error: string;
}

export function SpeakStudioScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  // Owned inputs minted via presignAndUpload — the only keys sent to the API.
  const [imageKey, setImageKey] = useState("");
  const [audioKey, setAudioKey] = useState("");
  const [imageUploading, setImageUploading] = useState(false);
  const [audioUploading, setAudioUploading] = useState(false);

  // Speak (talking avatar) generation.
  const [providers, setProviders] = useState<SpeakProvider[]>([]);
  const [provider, setProvider] = useState("");
  const [generation, setGeneration] = useState<SpeakGeneration | null>(null);
  const [generating, setGenerating] = useState(false);

  // Identity lock — reusable character + its reference sheet + LoRA training.
  const [characters, setCharacters] = useState<Character[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<CharacterDetail | null>(null);
  const [references, setReferences] = useState<CharacterReference[]>([]);
  const [binding, setBinding] = useState(false);
  const [training, setTraining] = useState<TrainingState | null>(null);

  const [error, setError] = useState("");
  const generationPoll = useRef<AbortController | null>(null);
  const trainingPoll = useRef<AbortController | null>(null);

  // --- Bootstrap: providers + saved characters (both degrade gracefully). ----
  useEffect(() => {
    const controller = new AbortController();
    let active = true;

    void listSpeakProviders({ token, signal: controller.signal })
      .then((result) => {
        if (active) setProviders(result.providers.filter((p) => p.available));
      })
      .catch(() => undefined);

    void listCharacters({ token, signal: controller.signal })
      .then((result) => {
        if (active) setCharacters(result.characters);
      })
      .catch(() => undefined);

    return () => {
      active = false;
      controller.abort();
    };
  }, [token]);

  // Cancel any in-flight polling loops on unmount.
  useEffect(
    () => () => {
      generationPoll.current?.abort();
      trainingPoll.current?.abort();
    },
    [],
  );

  // --- Identity: load a selected character's profile + references. -----------
  const loadCharacter = useCallback(
    async (characterId: string) => {
      const controller = new AbortController();
      setError("");
      try {
        const [profile, refs] = await Promise.all([
          getCharacter(characterId, { token, signal: controller.signal }),
          listCharacterReferences(characterId, {
            token,
            signal: controller.signal,
          }),
        ]);
        setDetail(profile);
        setReferences(refs);
      } catch (loadError) {
        if (!isAbortError(loadError)) setError(describe(loadError));
      }
    },
    [token],
  );

  const selectCharacter = (characterId: string) => {
    const next = characterId === selectedId ? "" : characterId;
    setSelectedId(next);
    setDetail(null);
    setReferences([]);
    setTraining(null);
    if (next) void loadCharacter(next);
  };

  // --- Uploads: mint the OWNED image_key / audio_key. ------------------------
  const chooseImage = async (source: "library" | "camera") => {
    setImageUploading(true);
    setError("");
    try {
      const file =
        source === "camera"
          ? await captureSelfie()
          : await pickSelfieFromLibrary();
      if (file) {
        const uploaded = await presignAndUpload(file, { token });
        setImageKey(uploaded.key);
      }
    } catch (uploadError) {
      setError(describe(uploadError));
    } finally {
      setImageUploading(false);
    }
  };

  const chooseAudio = async () => {
    setAudioUploading(true);
    setError("");
    try {
      const file = await pickVoiceSampleFromFiles();
      if (file) {
        const uploaded = await presignAndUpload(file, { token });
        setAudioKey(uploaded.key);
      }
    } catch (uploadError) {
      setError(describe(uploadError));
    } finally {
      setAudioUploading(false);
    }
  };

  // --- Identity: bind the uploaded selfie as a character reference. ----------
  const bindReference = async () => {
    if (!selectedId || !imageKey) return;
    setBinding(true);
    setError("");
    try {
      const ref = await addCharacterReference(
        selectedId,
        { r2_key: imageKey, role: "sheet", content_type: "image/jpeg" },
        { token },
      );
      setReferences((current) => [
        ref,
        ...current.filter((r) => r.r2_key !== ref.r2_key),
      ]);
    } catch (bindError) {
      setError(describe(bindError));
    } finally {
      setBinding(false);
    }
  };

  // --- Identity: train a LoRA, then poll it via GET /jobs/{id}. --------------
  const startTraining = async () => {
    if (!selectedId || references.length === 0) return;
    setError("");
    try {
      const started = await trainCharacter(selectedId, {}, { token });
      setTraining({
        jobId: started.job_id,
        state: JobState.Processing,
        progress: 0,
        error: "",
      });

      trainingPoll.current?.abort();
      const controller = new AbortController();
      trainingPoll.current = controller;
      await pollUntilTerminal({
        fetchSnapshot: (signal) =>
          getJob(started.job_id, { token, signal }),
        isTerminal: (job) => isTerminalState(job.state),
        onSnapshot: (job) =>
          setTraining({
            jobId: started.job_id,
            state: job.state,
            progress: job.progress,
            error: job.error ?? "",
          }),
        signal: controller.signal,
      });
      // Re-read the character so a freshly minted lora_ref shows up.
      await loadCharacter(selectedId);
    } catch (trainError) {
      if (!isAbortError(trainError)) setError(describe(trainError));
    }
  };

  // --- Speak: generate a talking video, then poll to completion. -------------
  const submit = async () => {
    if (!imageKey || !audioKey) return;
    setGenerating(true);
    setError("");
    try {
      const created = await generateSpeak(
        {
          image_key: imageKey,
          audio_key: audioKey,
          ...(provider ? { provider } : {}),
        },
        { token, idempotencyKey: newIdempotencyKey("speak") },
      );
      setGeneration(created);

      generationPoll.current?.abort();
      const controller = new AbortController();
      generationPoll.current = controller;
      if (!isTerminalState(created.state)) {
        await pollUntilTerminal({
          fetchSnapshot: (signal) =>
            getSpeakGeneration(created.generation_id, { token, signal }),
          isTerminal: (snapshot) => isTerminalState(snapshot.state),
          onSnapshot: setGeneration,
          signal: controller.signal,
        });
      }
    } catch (submitError) {
      if (!isAbortError(submitError)) setError(describe(submitError));
    } finally {
      setGenerating(false);
    }
  };

  const canGenerate = Boolean(imageKey && audioKey && !generating);
  const trainingBusy =
    training !== null && !isTerminalState(training.state);

  return (
    <ScrollView style={styles.page} contentContainerStyle={styles.content}>
      <Text style={styles.copy}>
        Lock a reusable identity, then turn an owned photo + narration audio into
        a talking avatar video.
      </Text>

      {/* -------------------------- Identity lock -------------------------- */}
      <Text style={styles.heading}>Identity lock</Text>
      <Text style={styles.hint}>
        Optionally pick a saved character to bind this photo as a reference and
        train a consistency LoRA.
      </Text>

      {characters.length === 0 ? (
        <Text style={styles.empty}>
          No saved characters yet. You can still generate a one-off talking
          avatar below.
        </Text>
      ) : (
        <ScrollView horizontal contentContainerStyle={styles.row}>
          {characters.map((character) => (
            <Pressable
              key={character.id}
              onPress={() => selectCharacter(character.id)}
              style={[
                styles.chip,
                selectedId === character.id && styles.chipActive,
              ]}
            >
              <Text style={styles.chipText}>{character.name}</Text>
            </Pressable>
          ))}
        </ScrollView>
      )}

      {selectedId ? (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>
            {detail ? detail.name : "Loading character…"}
          </Text>
          {detail ? (
            <>
              <Text style={styles.meta}>
                {references.length} reference
                {references.length === 1 ? "" : "s"}
                {detail.lora_ref ? " · identity LoRA trained" : ""}
              </Text>
              <View style={styles.row}>
                <Pressable
                  style={[
                    styles.secondary,
                    (!imageKey || binding) && styles.disabled,
                  ]}
                  disabled={!imageKey || binding}
                  onPress={() => void bindReference()}
                >
                  <Text style={styles.secondaryText}>
                    {binding ? "Binding…" : "Bind photo as reference"}
                  </Text>
                </Pressable>
                <Pressable
                  style={[
                    styles.secondary,
                    (references.length === 0 || trainingBusy) &&
                      styles.disabled,
                  ]}
                  disabled={references.length === 0 || trainingBusy}
                  onPress={() => void startTraining()}
                >
                  <Text style={styles.secondaryText}>
                    {trainingBusy ? "Training…" : "Train identity LoRA"}
                  </Text>
                </Pressable>
              </View>
              {training ? (
                <Text
                  style={
                    training.state === JobState.Failed
                      ? styles.error
                      : styles.meta
                  }
                >
                  {training.state === JobState.Complete
                    ? "Identity LoRA training complete."
                    : training.state === JobState.Failed
                      ? training.error || "Training failed."
                      : `Training ${progressPercent(training.progress)}%`}
                </Text>
              ) : null}
              {!imageKey ? (
                <Text style={styles.hint}>
                  Upload a photo below to bind it as a reference.
                </Text>
              ) : null}
            </>
          ) : (
            <ActivityIndicator color="#E6C76A" />
          )}
        </View>
      ) : null}

      {/* --------------------------- Talking avatar ------------------------ */}
      <Text style={styles.heading}>Talking avatar</Text>

      <View style={styles.row}>
        <Pressable
          style={[styles.secondary, imageUploading && styles.disabled]}
          disabled={imageUploading}
          onPress={() => void chooseImage("library")}
        >
          <Text style={styles.secondaryText}>
            {imageKey ? "Photo ready" : "Choose photo"}
          </Text>
        </Pressable>
        <Pressable
          style={[styles.secondary, imageUploading && styles.disabled]}
          disabled={imageUploading}
          onPress={() => void chooseImage("camera")}
        >
          <Text style={styles.secondaryText}>Take selfie</Text>
        </Pressable>
        {imageUploading ? <ActivityIndicator color="#E6C76A" /> : null}
      </View>

      <View style={styles.row}>
        <Pressable
          style={[styles.secondary, audioUploading && styles.disabled]}
          disabled={audioUploading}
          onPress={() => void chooseAudio()}
        >
          <Text style={styles.secondaryText}>
            {audioKey ? "Narration ready" : "Choose narration audio"}
          </Text>
        </Pressable>
        {audioUploading ? <ActivityIndicator color="#E6C76A" /> : null}
      </View>

      {providers.length ? (
        <View>
          <Text style={styles.hint}>Provider</Text>
          <ScrollView horizontal contentContainerStyle={styles.row}>
            <Pressable
              onPress={() => setProvider("")}
              style={[styles.chip, provider === "" && styles.chipActive]}
            >
              <Text style={styles.chipText}>Auto</Text>
            </Pressable>
            {providers.map((item) => (
              <Pressable
                key={item.provider}
                onPress={() => setProvider(item.provider)}
                style={[
                  styles.chip,
                  provider === item.provider && styles.chipActive,
                ]}
              >
                <Text style={styles.chipText}>{item.provider}</Text>
              </Pressable>
            ))}
          </ScrollView>
        </View>
      ) : null}

      {error ? (
        <View style={styles.errorBox}>
          <GenerationErrorNotice message={error} style={styles.error} />
        </View>
      ) : null}

      <Pressable
        style={[styles.primary, !canGenerate && styles.disabled]}
        disabled={!canGenerate}
        onPress={() => void submit()}
      >
        {generating ? (
          <ActivityIndicator color="#0f0f10" />
        ) : (
          <Text style={styles.primaryText}>Generate talking video</Text>
        )}
      </Pressable>

      {generation ? (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>
            {generation.state === JobState.Complete
              ? "Ready"
              : generation.state === JobState.Failed
                ? "Generation failed"
                : `Rendering ${progressPercent(generation.progress)}%`}
          </Text>
          <Text style={styles.meta} numberOfLines={1}>
            {generation.generation_id}
          </Text>

          {generation.state === JobState.Complete && generation.result_url ? (
            <JobVideo uri={generation.result_url} isLooping />
          ) : null}

          {generation.state === JobState.Failed && generation.error ? (
            <Text style={styles.error}>{generation.error}</Text>
          ) : null}

          {generation.state === JobState.Complete && generation.result_url ? (
            <Pressable
              style={styles.secondary}
              onPress={() => void Linking.openURL(generation.result_url)}
            >
              <Text style={styles.secondaryText}>Open full screen</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: "#0a0a0b" },
  content: { padding: 16, gap: 12, paddingBottom: 48 },
  copy: { color: "#9b978d", lineHeight: 20 },
  hint: { color: "#6f6c65", fontSize: 12 },
  heading: { color: "#ece9e1", fontSize: 18, fontWeight: "700", marginTop: 8 },
  row: { flexDirection: "row", flexWrap: "wrap", gap: 8, alignItems: "center" },
  chip: {
    borderWidth: 1,
    borderColor: "#27272a",
    borderRadius: 99,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  chipActive: { borderColor: "#E6C76A", backgroundColor: "#2a2416" },
  chipText: { color: "#ece9e1", fontSize: 13 },
  primary: {
    backgroundColor: "#E6C76A",
    borderRadius: 12,
    alignItems: "center",
    padding: 14,
    marginTop: 4,
  },
  primaryText: { color: "#0f0f10", fontWeight: "700" },
  secondary: {
    borderWidth: 1,
    borderColor: "#E6C76A",
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 9,
    alignSelf: "flex-start",
  },
  secondaryText: { color: "#E6C76A", fontWeight: "600" },
  disabled: { opacity: 0.5 },
  errorBox: {
    gap: 8,
    borderWidth: 1,
    borderColor: "#5b2a36",
    backgroundColor: "#24131a",
    borderRadius: 12,
    padding: 12,
  },
  error: { color: "#ff8b8b" },
  empty: { color: "#6f6c65", paddingVertical: 8 },
  card: {
    borderWidth: 1,
    borderColor: "#27272a",
    borderRadius: 14,
    padding: 12,
    gap: 10,
  },
  cardTitle: { color: "#ece9e1", fontWeight: "700" },
  meta: { color: "#6f6c65", fontSize: 12 },
});
