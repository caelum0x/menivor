import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Linking,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { useFocusEffect, useRouter } from "expo-router";

import { JobVideo } from "@/src/shared/media";
import { ContextualLinks } from "@/components/nav/ContextualLinks";
import {
  ApiError,
  generateBroll,
  getBrollGeneration,
  isAbortError,
  listBrollGenerations,
  listBrollPresets,
  presignAndUpload,
} from "@/lib/api";
import {
  loadBrollHistory,
  saveAttachedBrollKey,
  saveBrollHistory,
} from "@/src/shared/media";
import { pickSelfieFromLibrary } from "@/src/shared/media";
import { useSession } from "@/src/shared/auth";
import { useGenerationCapabilities } from "@/src/shared/hooks";
import { useAppStateStatus } from "@/src/shared/lifecycle";
import {
  JobState,
  isTerminalState,
  type BrollGenMode,
  type BrollGeneration,
  type BrollPreset,
} from "@/lib/types";
import { GenerationErrorNotice } from "@/components/billing/GenerationErrorNotice";

import { isBrollAvailable } from "./availability";

const POLL_MS = 3000;

function describe(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "Something went wrong.";
}

function mergeGenerations(
  preferred: readonly BrollGeneration[],
  fallback: readonly BrollGeneration[],
): BrollGeneration[] {
  const rows = new Map<string, BrollGeneration>();
  for (const item of fallback) rows.set(item.generation_id, item);
  for (const item of preferred) rows.set(item.generation_id, item);
  const preferredIds = new Set(preferred.map((item) => item.generation_id));
  return [
    ...preferred,
    ...fallback.filter((item) => !preferredIds.has(item.generation_id)),
  ].map((item) => rows.get(item.generation_id) ?? item);
}

function progressPercent(progress: number): number {
  // ReelForge generation progress is the same 0..100 scale as reel jobs.
  return Math.round(Math.max(0, Math.min(100, progress)));
}

function generationTitle(item: BrollGeneration): string {
  if (item.state === JobState.Complete) return "Ready to attach";
  if (item.state === JobState.Failed) return "Generation failed";
  return `Rendering ${progressPercent(item.progress)}%`;
}

export function BrollScreen() {
  const { apiKey } = useSession();
  const router = useRouter();
  const token = apiKey ?? undefined;
  const capabilityState = useGenerationCapabilities(token);
  const generationAllowed = isBrollAvailable(capabilityState.capabilities);

  const [prompt, setPrompt] = useState("");
  const [mode, setMode] = useState<BrollGenMode>("t2v");
  const [seed, setSeed] = useState("");
  const [presets, setPresets] = useState<BrollPreset[]>([]);
  const [workflowId, setWorkflowId] = useState("");
  const [imageKey, setImageKey] = useState("");
  const [items, setItems] = useState<BrollGeneration[]>([]);
  const [busy, setBusy] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [error, setError] = useState("");
  const appState = useAppStateStatus();
  const historyHydrated = useRef(false);
  const pendingCreate = useRef<{ signature: string; key: string } | null>(null);

  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      const remote = await listBrollGenerations({ token, signal });
      setItems((current) => mergeGenerations(remote, current));
      setError("");
    },
    [token],
  );

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    void (async () => {
      const cached = await loadBrollHistory(token);
      if (!active) return;
      setItems(cached);
      historyHydrated.current = true;
      setLoadingHistory(false);

      try {
        await refresh(controller.signal);
      } catch (refreshError) {
        if (!isAbortError(refreshError) && active && cached.length === 0) {
          setError(describe(refreshError));
        }
      }
    })();

    void listBrollPresets({ token, signal: controller.signal })
      .then((rows) => {
        if (active) setPresets(rows);
      })
      .catch(() => undefined);

    return () => {
      active = false;
      controller.abort();
    };
  }, [refresh, token]);

  useFocusEffect(
    useCallback(() => {
      if (appState !== "active") return undefined;
      const controller = new AbortController();
      void refresh(controller.signal).catch((refreshError) => {
        if (!isAbortError(refreshError)) setError(describe(refreshError));
      });
      return () => controller.abort();
    }, [appState, refresh]),
  );

  useEffect(() => {
    if (!historyHydrated.current) return;
    const timer = setTimeout(() => {
      void saveBrollHistory(token, items);
    }, 250);
    return () => clearTimeout(timer);
  }, [items, token]);

  const pendingIds = useMemo(
    () =>
      items
        .filter((item) => !isTerminalState(item.state))
        .map((item) => item.generation_id),
    [items],
  );
  const pendingKey = pendingIds.join(":");

  useEffect(() => {
    if (appState !== "active" || pendingIds.length === 0) return undefined;
    const controller = new AbortController();
    let inFlight = false;
    let active = true;
    const tick = () => {
      if (inFlight) return;
      inFlight = true;
      void Promise.all(
        pendingIds.map((id) =>
          getBrollGeneration(id, { token, signal: controller.signal }),
        ),
      )
        .then((updates) => {
          if (active) setItems((current) => mergeGenerations(updates, current));
        })
        .catch((pollError) => {
          if (active && !isAbortError(pollError)) setError(describe(pollError));
        })
        .finally(() => {
          inFlight = false;
        });
    };
    tick();
    const timer = setInterval(tick, POLL_MS);

    return () => {
      active = false;
      clearInterval(timer);
      controller.abort();
    };
    // pendingKey deliberately restarts polling only as the pending set changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appState, pendingKey, token]);

  const chooseImage = async () => {
    setBusy(true);
    setError("");
    try {
      const image = await pickSelfieFromLibrary();
      if (image) {
        const uploaded = await presignAndUpload(image, { token });
        setImageKey(uploaded.key);
      }
    } catch (chooseError) {
      setError(describe(chooseError));
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    if (!generationAllowed) {
      setError(
        capabilityState.error ||
          "AI B-roll is not available on this account yet.",
      );
      return;
    }
    const cleanPrompt = prompt.trim();
    if (!cleanPrompt || (mode === "i2v" && !imageKey)) return;
    setBusy(true);
    setError("");
    try {
      const parsedSeed = Number(seed);
      const body = {
        prompt: cleanPrompt,
        mode,
        ...(imageKey ? { image_key: imageKey } : {}),
        ...(workflowId ? { workflow_id: workflowId } : {}),
        ...(seed.trim() && Number.isFinite(parsedSeed)
          ? { seed: parsedSeed }
          : {}),
      };
      const signature = JSON.stringify(body);
      if (!pendingCreate.current || pendingCreate.current.signature !== signature) {
        pendingCreate.current = {
          signature,
          key: `mobile-broll-${Date.now()}-${Math.random().toString(36).slice(2)}`,
        };
      }
      const created = await generateBroll(body, {
        token,
        idempotencyKey: pendingCreate.current.key,
      });
      pendingCreate.current = null;
      setItems((current) => mergeGenerations([created], current));
      setPrompt("");
    } catch (submitError) {
      setError(describe(submitError));
    } finally {
      setBusy(false);
    }
  };

  const attachToReel = async (item: BrollGeneration) => {
    if (!item.broll_key) return;
    await saveAttachedBrollKey(token, item.broll_key);
    router.push({
      pathname: "/(tabs)/create",
      params: { broll_key: item.broll_key },
    });
  };

  if (capabilityState.loading) {
    return (
      <View style={[styles.page, styles.centered]}>
        <ActivityIndicator color="#E6C76A" />
        <Text style={styles.copy}>Checking B-roll availability…</Text>
      </View>
    );
  }

  if (!generationAllowed) {
    return (
      <View style={[styles.page, styles.centered]}>
        <Text style={styles.title}>AI B-roll is unavailable</Text>
        <Text style={styles.copy}>
          {capabilityState.error ||
            "AI B-roll is not available on this account yet. You can still make reels from the Create tab."}
        </Text>
      </View>
    );
  }

  return (
    <ScrollView style={styles.page} contentContainerStyle={styles.content}>
      <Text style={styles.copy}>
        Generate a short motion cutaway, preview it here, then attach it to a
        new reel.
      </Text>

      <View style={styles.row}>
        {(["t2v", "i2v"] as const).map((value) => (
          <Pressable
            key={value}
            onPress={() => setMode(value)}
            style={[styles.chip, mode === value && styles.chipActive]}
          >
            <Text style={styles.chipText}>
              {value === "t2v" ? "Text to video" : "Image to video"}
            </Text>
          </Pressable>
        ))}
      </View>

      <TextInput
        style={[styles.input, styles.prompt]}
        multiline
        value={prompt}
        onChangeText={setPrompt}
        placeholder="Describe the shot and its motion"
        placeholderTextColor="#6f6c65"
      />
      <TextInput
        style={styles.input}
        value={seed}
        onChangeText={setSeed}
        keyboardType="numeric"
        placeholder="Seed (optional)"
        placeholderTextColor="#6f6c65"
      />

      {presets.length ? (
        <ScrollView horizontal contentContainerStyle={styles.row}>
          {presets.map((preset) => (
            <Pressable
              key={preset.id}
              style={styles.chip}
              onPress={() => {
                setMode(preset.mode);
                setWorkflowId(preset.workflow_id);
                if (preset.prompt_template) setPrompt(preset.prompt_template);
              }}
            >
              <Text style={styles.chipText}>{preset.name}</Text>
            </Pressable>
          ))}
        </ScrollView>
      ) : null}

      {mode === "i2v" ? (
        <Pressable
          style={styles.secondary}
          onPress={() => void chooseImage()}
          disabled={busy}
        >
          <Text style={styles.secondaryText}>
            {imageKey ? "Reference image ready" : "Choose reference image"}
          </Text>
        </Pressable>
      ) : null}

      {error ? (
        <View style={styles.errorBox}>
          <GenerationErrorNotice message={error} style={styles.error} />
          <Pressable onPress={() => void refresh()}>
            <Text style={styles.retryText}>Refresh history</Text>
          </Pressable>
        </View>
      ) : null}

      <Pressable
        style={[styles.primary, busy && styles.disabled]}
        disabled={busy || !prompt.trim() || (mode === "i2v" && !imageKey)}
        onPress={() => void submit()}
      >
        {busy ? (
          <ActivityIndicator color="#0f0f10" />
        ) : (
          <Text style={styles.primaryText}>Generate B-roll</Text>
        )}
      </Pressable>

      <View style={styles.sectionHeader}>
        <Text style={styles.heading}>Recent generations</Text>
        <Pressable onPress={() => void refresh()}>
          <Text style={styles.retryText}>Refresh</Text>
        </Pressable>
      </View>

      {loadingHistory ? <ActivityIndicator color="#E6C76A" /> : null}
      {!loadingHistory && items.length === 0 ? (
        <Text style={styles.empty}>Your generated clips will appear here.</Text>
      ) : null}

      {items.map((item) => (
        <View key={item.generation_id} style={styles.card}>
          <View style={styles.cardHeader}>
            <View style={styles.cardCopy}>
              <Text style={styles.cardTitle}>{generationTitle(item)}</Text>
              <Text style={styles.meta} numberOfLines={1}>
                {item.generation_id}
              </Text>
            </View>
            {!isTerminalState(item.state) ? (
              <Text style={styles.progress}>{progressPercent(item.progress)}%</Text>
            ) : null}
          </View>

          {item.state === JobState.Complete && item.result_url ? (
            <JobVideo uri={item.result_url} isLooping isMuted />
          ) : null}

          {item.state === JobState.Failed && item.error ? (
            <Text style={styles.error}>{item.error}</Text>
          ) : null}

          {item.state === JobState.Complete && item.broll_key ? (
            <View style={styles.row}>
              <Pressable
                style={styles.primarySmall}
                onPress={() => void attachToReel(item)}
              >
                <Text style={styles.primaryText}>Attach to reel</Text>
              </Pressable>
              {item.result_url ? (
                <Pressable
                  style={styles.secondary}
                  onPress={() => void Linking.openURL(item.result_url!)}
                >
                  <Text style={styles.secondaryText}>Open full screen</Text>
                </Pressable>
              ) : null}
            </View>
          ) : null}
        </View>
      ))}

      <ContextualLinks context="broll" title="Feed your B-roll" />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: "#0a0a0b" },
  centered: {
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
    gap: 12,
  },
  title: { color: "#ece9e1", fontSize: 18, fontWeight: "700" },
  content: { padding: 16, gap: 12, paddingBottom: 48 },
  copy: { color: "#9b978d", lineHeight: 20 },
  row: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  sectionHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: 8,
  },
  chip: {
    borderWidth: 1,
    borderColor: "#27272a",
    borderRadius: 99,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  chipActive: { borderColor: "#E6C76A", backgroundColor: "#2a2416" },
  chipText: { color: "#ece9e1", fontSize: 13 },
  input: {
    borderWidth: 1,
    borderColor: "#27272a",
    borderRadius: 12,
    color: "#ece9e1",
    padding: 12,
  },
  prompt: { minHeight: 110, textAlignVertical: "top" },
  primary: {
    backgroundColor: "#E6C76A",
    borderRadius: 12,
    alignItems: "center",
    padding: 14,
  },
  primarySmall: {
    backgroundColor: "#E6C76A",
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
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
  retryText: { color: "#E6C76A", fontWeight: "700" },
  heading: { color: "#ece9e1", fontSize: 18, fontWeight: "700" },
  empty: { color: "#6f6c65", paddingVertical: 12 },
  card: {
    borderWidth: 1,
    borderColor: "#27272a",
    borderRadius: 14,
    padding: 12,
    gap: 12,
  },
  cardHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  cardCopy: { flex: 1 },
  cardTitle: { color: "#ece9e1", fontWeight: "700" },
  meta: { color: "#6f6c65", fontSize: 11, marginTop: 3 },
  progress: { color: "#E6C76A", fontWeight: "800" },
});
