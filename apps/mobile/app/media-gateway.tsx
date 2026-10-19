/**
 * Media gateway screen — OpenRouter-style one key + one balance.
 *
 * Three segments: Generate (image sync / video submit + poll), Models (unified
 * catalog), and Usage (spendable credits + spend-by-model). Renders images with
 * RN <Image>; opens finished videos in the browser (no extra AV dependency).
 */

import { Icon } from "@/components/ui/Icon";
import * as React from "react";
import {
  ActivityIndicator,
  Image,
  Linking,
  Pressable,
  ScrollView,
  Share,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { colors } from "@/components/me/theme";
import { useSession } from "@/src/shared/auth";
import {
  cancelAudio,
  cancelVideo,
  createAudio,
  createImage,
  createVideo,
  estimateCostMicros,
  formatUsdMicros,
  getAudio,
  getGeneration,
  getGenerationEvidence,
  getGenerationProvenance,
  getCredits,
  getUsage,
  getVideo,
  isTerminalStatus,
  listGenerations,
  listIdentityOptions,
  listMediaModels,
  priceLabel,
  settlementProofView,
  type Credits,
  type GenerationDetail,
  type IdentityOption,
  type MediaModel,
  type Modality,
  type UsageRow,
} from "@/lib/media-gateway";

const POLL_MS = 3000;
/** Ceiling for a single generation poll; a longer job surfaces as "still processing". */
const MAX_POLL_MS = 5 * 60 * 1000;
type Segment = "generate" | "models" | "usage";

export default function MediaGatewayScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const [segment, setSegment] = React.useState<Segment>("generate");

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.intro}>
        One key, one balance — generate with any image or video model, and track your spend.
      </Text>

      <View style={styles.segments}>
        {(["generate", "models", "usage"] as Segment[]).map((s) => (
          <Pressable
            key={s}
            style={[styles.segment, segment === s && styles.segmentActive]}
            onPress={() => setSegment(s)}
          >
            <Text style={[styles.segmentText, segment === s && styles.segmentTextActive]}>
              {s === "generate" ? "Generate" : s === "models" ? "Models" : "Usage"}
            </Text>
          </Pressable>
        ))}
      </View>

      {segment === "generate" ? <GeneratePanel token={token} /> : null}
      {segment === "models" ? <ModelsPanel token={token} /> : null}
      {segment === "usage" ? <UsagePanel token={token} /> : null}

      <View style={styles.spacer} />
    </ScrollView>
  );
}

/** Video duration this panel submits (seconds); shared by the cost estimate. */
const VIDEO_DURATION_S = 5;

function GeneratePanel({ token }: { token: string | undefined }) {
  const [modality, setModality] = React.useState<Modality>("image");
  const [models, setModels] = React.useState<MediaModel[]>([]);
  const [model, setModel] = React.useState("");
  const [prompt, setPrompt] = React.useState("");
  const [referenceImageUrl, setReferenceImageUrl] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [imageUrl, setImageUrl] = React.useState("");
  const [videoUrl, setVideoUrl] = React.useState("");
  const [audioUrl, setAudioUrl] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [cost, setCost] = React.useState<number | null>(null);
  const [credits, setCredits] = React.useState<Credits | null>(null);
  const [creditsLoading, setCreditsLoading] = React.useState(true);
  const [history, setHistory] = React.useState<GenerationDetail[]>([]);
  const [identities, setIdentities] = React.useState<IdentityOption[]>([]);
  const [identityKey, setIdentityKey] = React.useState("");
  const [inspectedEntry, setInspectedEntry] = React.useState<GenerationDetail | null>(null);
  const [exportingProof, setExportingProof] = React.useState(false);
  const [exportingEvidence, setExportingEvidence] = React.useState(false);
  const [cancelling, setCancelling] = React.useState(false);
  const preferImageToVideo = React.useRef(false);
  // Tracks the in-flight async (video/audio) job so it can be cancelled mid-poll
  // to release the held credits (success-only billing).
  const activeJobIdRef = React.useRef<string | null>(null);
  const cancelRequestedRef = React.useRef(false);
  const settlementProof = inspectedEntry ? settlementProofView(inspectedEntry) : null;

  const refreshHistory = React.useCallback(async () => {
    try {
      const page = await listGenerations(
        { limit: 24, refreshPending: true },
        { token },
      );
      setHistory(page.generations);
    } catch {
      // Generation controls remain available if history recovery is unavailable.
    }
  }, [token]);

  const openEntry = React.useCallback(async (entry: GenerationDetail) => {
    setError("");
    setStatus("");
    let current = entry;
    if (!entry.is_terminal) {
      try {
        current = await getGeneration(entry.id, { token });
        setHistory((items) => items.map((item) => item.id === current.id ? current : item));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Resume failed.");
      }
    }
    setInspectedEntry(current);
    setImageUrl(current.modality === "image" ? current.output_url || "" : "");
    setVideoUrl(current.modality === "video" ? current.output_url || "" : "");
    setAudioUrl(current.modality === "audio" ? current.output_url || "" : "");
    setCost(current.effective_cost_micros);
    setModality(current.modality);
  }, [token]);

  const refreshCredits = React.useCallback(async () => {
    setCreditsLoading(true);
    try {
      setCredits(await getCredits({ token }));
    } catch {
      setCredits(null);
    } finally {
      setCreditsLoading(false);
    }
  }, [token]);

  React.useEffect(() => {
    void refreshCredits();
    void refreshHistory();
  }, [refreshCredits, refreshHistory]);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { models: rows } = await listMediaModels(modality, { token });
        if (cancelled) return;
        setModels(rows);
        setModel((prev) => {
          if (rows.some((m) => m.id === prev)) return prev;
          if (modality === "video" && preferImageToVideo.current) {
            preferImageToVideo.current = false;
            return rows.find((m) => m.id.toLowerCase().includes("i2v"))?.id ?? rows[0]?.id ?? "";
          }
          return rows[0]?.id ?? "";
        });
      } catch {
        if (!cancelled) setModels([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [modality, token]);

  React.useEffect(() => {
    if (modality !== "video") return;
    let cancelled = false;
    (async () => {
      try {
        const { identities: rows } = await listIdentityOptions({ token });
        if (cancelled) return;
        setIdentities(rows);
        setIdentityKey((current) =>
          current && rows.some((row) => `${row.passport_id}:${row.version}` === current)
            ? current
            : "",
        );
      } catch {
        if (!cancelled) setIdentities([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [modality, token]);

  const reset = () => {
    setError("");
    setImageUrl("");
    setVideoUrl("");
    setAudioUrl("");
    setStatus("");
    setCost(null);
    cancelRequestedRef.current = false;
    activeJobIdRef.current = null;
  };

  const run = React.useCallback(async () => {
    if (!model || !prompt.trim() || busy) return;
    reset();
    setBusy(true);
    try {
      if (modality === "image") {
        const result = await createImage({ model, prompt: prompt.trim() }, { token });
        setImageUrl(result.url);
        setCost(result.cost_micros);
      } else {
        // video + audio are both async submit→poll.
        const job =
          modality === "audio"
            ? await createAudio({ model, prompt: prompt.trim() }, { token })
            : await createVideo(
                {
                  model,
                  prompt: prompt.trim(),
                  duration: VIDEO_DURATION_S,
                  aspect_ratio: "9:16",
                  image_url: referenceImageUrl.trim() || undefined,
                  identity_passport_id: identities.find(
                    (item) => `${item.passport_id}:${item.version}` === identityKey,
                  )?.passport_id,
                  identity_version: identities.find(
                    (item) => `${item.passport_id}:${item.version}` === identityKey,
                  )?.version,
                },
                { token },
              );
        setStatus(job.status);
        setCost(job.cost_micros);
        // Expose the job id so the Cancel action can release the hold mid-flight.
        activeJobIdRef.current = job.id;
        // Poll to terminal, bounded so a stuck job surfaces instead of hanging.
        const deadline = Date.now() + MAX_POLL_MS;
        let current = job;
        let timedOut = false;
        while (!isTerminalStatus(current.status)) {
          if (cancelRequestedRef.current) break;
          if (Date.now() >= deadline) {
            timedOut = true;
            break;
          }
          await new Promise((r) => setTimeout(r, POLL_MS));
          if (cancelRequestedRef.current) break;
          current =
            modality === "audio"
              ? await getAudio(job.id, { token })
              : await getVideo(job.id, { token });
          setStatus(current.status);
        }
        if (cancelRequestedRef.current) {
          setStatus(current.status);
          setError("Generation cancelled — the held credits were released.");
        } else if (timedOut) {
          setError("Still processing — it'll appear in your jobs when ready.");
        } else if (current.status === "completed") {
          if (modality === "audio") setAudioUrl(current.url);
          else setVideoUrl(current.url);
          setCost(current.cost_micros);
        } else {
          setError(current.error || "Generation failed.");
        }
        activeJobIdRef.current = null;
      }
      void refreshCredits(); // settle: debit on success, release on failure
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed.");
    } finally {
      void refreshHistory();
      setBusy(false);
    }
  }, [model, prompt, busy, modality, referenceImageUrl, identities, identityKey, token, refreshCredits, refreshHistory]);

  const cancelActive = React.useCallback(async () => {
    const jobId = activeJobIdRef.current;
    if (!jobId || cancelling) return;
    setCancelling(true);
    setError("");
    // Signal the poll loop to stop, then release the hold server-side.
    cancelRequestedRef.current = true;
    try {
      if (modality === "audio") await cancelAudio(jobId, { token });
      else await cancelVideo(jobId, { token });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Cancel failed.");
    } finally {
      setCancelling(false);
      void refreshCredits();
      void refreshHistory();
    }
  }, [cancelling, modality, token, refreshCredits, refreshHistory]);

  const exportEvidence = React.useCallback(async () => {
    if (!inspectedEntry) return;
    setExportingEvidence(true);
    setError("");
    try {
      const evidence = await getGenerationEvidence(inspectedEntry.id, { token });
      await Share.share({
        title: `Menivor settlement evidence ${inspectedEntry.id}`,
        message: `${JSON.stringify(evidence, null, 2)}\n`,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Evidence export failed.");
    } finally {
      setExportingEvidence(false);
    }
  }, [inspectedEntry, token]);

  const exportProvenance = React.useCallback(async () => {
    if (!inspectedEntry?.identity) return;
    setExportingProof(true);
    setError("");
    try {
      const proof = await getGenerationProvenance(inspectedEntry.id, { token });
      await Share.share({
        title: `Menivor provenance ${inspectedEntry.id}`,
        message: `${JSON.stringify(proof, null, 2)}\n`,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Proof export failed.");
    } finally {
      setExportingProof(false);
    }
  }, [inspectedEntry, token]);

  const selected = models.find((m) => m.id === model);
  const imageRequired = modality === "video" && selected?.id.toLowerCase().includes("i2v");
  const estimate = estimateCostMicros(selected, modality, VIDEO_DURATION_S);
  const available = credits?.available_micros ?? 0;
  // Guard only once the balance has loaded, so we don't flash "insufficient".
  const affordable = creditsLoading || credits === null || estimate <= available;
  const canRun =
    !!model &&
    !!prompt.trim() &&
    (!imageRequired || !!referenceImageUrl.trim()) &&
    !busy &&
    affordable;

  const animateImage = React.useCallback((url: string) => {
    preferImageToVideo.current = true;
    setReferenceImageUrl(url);
    setModality("video");
    setVideoUrl("");
    setAudioUrl("");
    setError("");
  }, []);

  return (
    <View>
      <View style={styles.walletBar}>
        <Text style={styles.walletLabel}>Wallet balance</Text>
        <Text style={styles.walletValue}>
          {creditsLoading && credits === null ? "…" : credits ? formatUsdMicros(available) : "—"}
          {credits && credits.reserved_micros > 0 ? (
            <Text style={styles.walletHeld}> ({formatUsdMicros(credits.reserved_micros)} held)</Text>
          ) : null}
        </Text>
      </View>

      <View style={styles.toggleRow}>
        {(["image", "video", "audio"] as Modality[]).map((mod) => (
          <Pressable
            key={mod}
            style={[styles.toggle, modality === mod && styles.toggleActive]}
            onPress={() => {
              setModality(mod);
              reset();
            }}
          >
            <Text style={[styles.toggleText, modality === mod && styles.toggleTextActive]}>
              {mod === "image" ? "Image" : mod === "video" ? "Video" : "Audio"}
            </Text>
          </Pressable>
        ))}
      </View>

      <Text style={styles.label}>Model</Text>
      <View style={styles.modelList}>
        {models.map((m) => (
          <Pressable
            key={m.id}
            style={[styles.modelChip, model === m.id && styles.modelChipActive]}
            onPress={() => setModel(m.id)}
          >
            <Text style={[styles.modelChipText, model === m.id && styles.modelChipTextActive]}>
              {m.id}
            </Text>
            <Text style={styles.modelChipPrice}>{priceLabel(m)}</Text>
          </Pressable>
        ))}
        {models.length === 0 ? <Text style={styles.meta}>No models available.</Text> : null}
      </View>

      <Text style={styles.label}>Prompt</Text>
      <TextInput
        style={styles.input}
        value={prompt}
        onChangeText={setPrompt}
        placeholder="A red panda surfing a neon wave, cinematic…"
        placeholderTextColor={colors.muted}
        multiline
        editable={!busy}
      />

      {modality === "video" ? (
        <View style={styles.sourcePanel}>
          <Text style={styles.label}>
            Source image {imageRequired ? "(required)" : "(optional)"}
          </Text>
          <TextInput
            style={[styles.input, styles.urlInput]}
            value={referenceImageUrl}
            onChangeText={setReferenceImageUrl}
            placeholder="https://…"
            placeholderTextColor={colors.muted}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
            editable={!busy}
          />
          <Text style={styles.meta}>
            Use a generated image or paste a public image URL to create an image-to-video shot.
          </Text>
          <Text style={styles.label}>Identity Lock (optional)</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.identityRow}>
            <Pressable
              style={[styles.identityChip, identityKey === "" && styles.identityChipActive]}
              onPress={() => setIdentityKey("")}
            >
              <Text style={styles.identityChipText}>No passport</Text>
            </Pressable>
            {identities.map((identity) => {
              const key = `${identity.passport_id}:${identity.version}`;
              return (
                <Pressable
                  key={key}
                  style={[styles.identityChip, identityKey === key && styles.identityChipActive]}
                  onPress={() => setIdentityKey(key)}
                >
                  <Text style={styles.identityChipText}>{identity.kind} · v{identity.version}</Text>
                  <Text style={styles.identityDigest} numberOfLines={1}>{identity.content_digest}</Text>
                </Pressable>
              );
            })}
          </ScrollView>
          <Text style={styles.meta}>
            Resolves the exact locked digest before provider execution. Video reference conditioning only.
          </Text>
        </View>
      ) : null}

      <Pressable
        style={[styles.button, !canRun && styles.buttonDisabled]}
        onPress={run}
        disabled={!canRun}
      >
        {busy ? (
          <ActivityIndicator color={colors.bg} />
        ) : (
          <Text style={styles.buttonText}>
            {selected ? `Generate · ~${formatUsdMicros(estimate)}` : "Generate"}
          </Text>
        )}
      </Pressable>

      {busy && modality !== "image" ? (
        <Pressable
          style={[styles.cancelButton, cancelling && styles.buttonDisabled]}
          onPress={cancelActive}
          disabled={cancelling}
          accessibilityRole="button"
          accessibilityLabel="Cancel this generation and release the held credits"
        >
          {cancelling ? (
            <ActivityIndicator color={colors.error} />
          ) : (
            <Text style={styles.cancelText}>Cancel &amp; release hold</Text>
          )}
        </Pressable>
      ) : null}

      {selected && credits !== null && !creditsLoading && estimate > available ? (
        <Text style={styles.insufficient}>
          Insufficient balance — need {formatUsdMicros(estimate)}, have {formatUsdMicros(available)}.
        </Text>
      ) : null}

      {status && !videoUrl && !audioUrl && !error ? (
        <Text style={styles.meta}>Status: {status}…</Text>
      ) : null}
      {error ? (
        <View style={styles.errorRow}>
          <Text style={[styles.error, styles.errorText]}>{error}</Text>
          <Pressable style={[styles.retryBtn, !canRun && styles.buttonDisabled]} onPress={run} disabled={!canRun}>
            <Text style={styles.retryText}>Try again</Text>
          </Pressable>
        </View>
      ) : null}

      {imageUrl ? (
        <View style={styles.card}>
          {cost !== null ? <Text style={styles.badge}>{formatUsdMicros(cost)}</Text> : null}
          <Image source={{ uri: imageUrl }} style={styles.preview} resizeMode="contain" />
          <Pressable style={[styles.button, styles.animateButton]} onPress={() => animateImage(imageUrl)}>
            <Text style={styles.buttonText}>Animate image</Text>
          </Pressable>
        </View>
      ) : null}

      {videoUrl ? (
        <View style={styles.card}>
          {cost !== null ? <Text style={styles.badge}>{formatUsdMicros(cost)}</Text> : null}
          <Pressable style={styles.button} onPress={() => void Linking.openURL(videoUrl)}>
            <Text style={styles.buttonText}>Open video</Text>
          </Pressable>
        </View>
      ) : null}

      {audioUrl ? (
        <View style={styles.card}>
          {cost !== null ? <Text style={styles.badge}>{formatUsdMicros(cost)}</Text> : null}
          <Pressable style={styles.button} onPress={() => void Linking.openURL(audioUrl)}>
            <Text style={styles.buttonText}>Open audio</Text>
          </Pressable>
        </View>
      ) : null}

      {history.length > 0 ? (
        <View style={styles.historySection}>
          <Text style={styles.historyTitle}>History ({history.length})</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.historyRow}>
            {history.map((entry) => {
              const entrySettlement = settlementProofView(entry);
              return <Pressable
                key={entry.id}
                style={styles.historyTile}
                onPress={() => openEntry(entry)}
              >
                {entry.modality === "image" && entry.output_url ? (
                  <Image source={{ uri: entry.output_url }} style={styles.historyThumb} resizeMode="cover" />
                ) : (
                  <View style={[styles.historyThumb, styles.historyIcon]}>
                    <Icon name={entry.modality === "video" ? "play" : "musical-notes"} style={styles.historyIconText} />
                  </View>
                )}
                <Text style={styles.historyModel} numberOfLines={1}>
                  {entry.model}
                </Text>
                <Text style={styles.historyCost} numberOfLines={1}>
                  {entry.status === "failed" && entry.error
                    ? `${entry.error} · ${entrySettlement.chargeLabel}`
                    : `${entrySettlement.outcomeLabel} · ${entrySettlement.chargeLabel}`}
                </Text>
                {entry.identity ? (
                  <Text style={styles.identityStatus} numberOfLines={1}>
                    Verified v{entry.identity.version} · {entry.identity.status}
                  </Text>
                ) : null}
              </Pressable>;
            })}
          </ScrollView>
        </View>
      ) : null}

      {inspectedEntry && settlementProof ? (
        <View style={styles.proofCard}>
          <View style={styles.proofHeader}>
            <Text style={styles.proofTitle}>Settlement proof</Text>
            {inspectedEntry.is_terminal ? (
              <Pressable
                style={[styles.proofButton, exportingEvidence && styles.buttonDisabled]}
                disabled={exportingEvidence}
                onPress={() => void exportEvidence()}
                accessibilityRole="button"
                accessibilityLabel="Share the signed settlement evidence as JSON"
              >
                <Text style={styles.retryText}>
                  {exportingEvidence ? "Exporting…" : "Share evidence"}
                </Text>
              </Pressable>
            ) : null}
          </View>
          <Text style={styles.meta}>{settlementProof.proofLabel}</Text>
          <ProofField label="Status" value={inspectedEntry.status} />
          <ProofField label="Settlement outcome" value={settlementProof.outcomeLabel} />
          <ProofField label="Charge" value={settlementProof.chargeLabel} />
          <ProofField label="Request" value={inspectedEntry.correlation_id} />
          <ProofField label="Executor" value={inspectedEntry.execution.kind} />
          <ProofField label="Provider request" value={inspectedEntry.provider_request_id || "pending"} />
          <ProofField label="Receipt operation" value={settlementProof.operation || "not available"} />
          <ProofField label="Receipt hash" value={settlementProof.receiptHash || "not available"} />
          <ProofField label="Receipt signature" value={settlementProof.signature || "not available"} />
          <ProofField label="Error" value={inspectedEntry.error || "none"} />
        </View>
      ) : null}

      {inspectedEntry?.identity ? (
        <View style={styles.proofCard}>
          <View style={styles.proofHeader}>
            <View>
              <Text style={styles.proofTitle}>Signed provenance</Text>
              <Text style={styles.meta}>
                {inspectedEntry.identity.status} · passport v{inspectedEntry.identity.version}
              </Text>
            </View>
            <Pressable
              style={[styles.proofButton, exportingProof && styles.buttonDisabled]}
              disabled={exportingProof}
              onPress={() => void exportProvenance()}
            >
              <Text style={styles.retryText}>{exportingProof ? "Exporting…" : "Share JSON"}</Text>
            </Pressable>
          </View>
          <ProofField label="Passport" value={inspectedEntry.identity.passport_id} />
          <ProofField label="Digest" value={inspectedEntry.identity.content_digest} />
          <ProofField label="Output" value={inspectedEntry.output_url || "pending"} />
          <ProofField label="Payer" value={inspectedEntry.identity.payer_account || "pending"} />
          <ProofField label="Request" value={inspectedEntry.identity.request_id || "pending"} />
          <ProofField label="Provenance ID" value={inspectedEntry.identity.provenance_id || "pending"} />
          <ProofField label="Receipt hash" value={inspectedEntry.identity.receipt?.receipt_hash || "pending"} />
          <ProofField label="Signature" value={inspectedEntry.identity.receipt?.signature || "pending"} />
        </View>
      ) : null}
    </View>
  );
}

function ProofField({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.proofField}>
      <Text style={styles.proofLabel}>{label}</Text>
      <Text style={styles.proofValue} numberOfLines={1}>{value}</Text>
    </View>
  );
}

function ModelsPanel({ token }: { token: string | undefined }) {
  const [models, setModels] = React.useState<MediaModel[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const { models: rows } = await listMediaModels(undefined, { token });
        if (!cancelled) setModels(rows);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (loading) return <ActivityIndicator color={colors.primary} style={styles.loading} />;
  if (error) return <Text style={styles.error}>{error}</Text>;

  return (
    <View>
      {models.map((m) => (
        <View key={m.id} style={styles.card}>
          <Text style={styles.name}>{m.id}</Text>
          <Text style={styles.meta}>
            {m.modality} · {m.provider} · {priceLabel(m)}
            {m.modality === "video" && m.max_seconds ? ` · ≤ ${m.max_seconds}s` : ""}
          </Text>
          {m.description ? <Text style={styles.desc}>{m.description}</Text> : null}
        </View>
      ))}
    </View>
  );
}

function UsagePanel({ token }: { token: string | undefined }) {
  const [credits, setCredits] = React.useState<Credits | null>(null);
  const [usage, setUsage] = React.useState<UsageRow[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [c, u] = await Promise.all([getCredits({ token }), getUsage({ token })]);
        if (cancelled) return;
        setCredits(c);
        setUsage(u.usage);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (loading) return <ActivityIndicator color={colors.primary} style={styles.loading} />;
  if (error) return <Text style={styles.error}>{error}</Text>;

  return (
    <View>
      <View style={styles.statsRow}>
        <View style={styles.stat}>
          <Text style={styles.statLabel}>Available</Text>
          <Text style={styles.statValue}>
            {credits ? formatUsdMicros(credits.available_micros) : "—"}
          </Text>
        </View>
        <View style={styles.stat}>
          <Text style={styles.statLabel}>Lifetime spend</Text>
          <Text style={styles.statValue}>
            {credits ? formatUsdMicros(credits.total_gateway_spend_micros) : "—"}
          </Text>
        </View>
      </View>

      <Text style={styles.label}>Spend by model</Text>
      {usage.map((r) => (
        <View key={r.model} style={styles.usageRow}>
          <View style={styles.usageLeft}>
            <Text style={styles.name}>{r.model}</Text>
            <Text style={styles.meta}>
              {r.modality} · {r.jobs} jobs{r.seconds ? ` · ${r.seconds}s` : ""}
            </Text>
          </View>
          <Text style={styles.usageSpend}>{formatUsdMicros(r.spend_micros)}</Text>
        </View>
      ))}
      {usage.length === 0 ? (
        <Text style={styles.meta}>No usage yet — run a generation to see spend here.</Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  intro: { color: colors.textSecondary, fontSize: 14, marginBottom: 16 },
  segments: { flexDirection: "row", gap: 8, marginBottom: 16 },
  segment: {
    flex: 1,
    paddingVertical: 10,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
    alignItems: "center",
  },
  segmentActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  segmentText: { color: colors.textSecondary, fontSize: 14, fontWeight: "600" },
  segmentTextActive: { color: colors.bg },
  toggleRow: { flexDirection: "row", gap: 8, marginBottom: 14 },
  toggle: {
    paddingVertical: 8,
    paddingHorizontal: 20,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
  },
  toggleActive: { backgroundColor: colors.cardAlt, borderColor: colors.accent },
  toggleText: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  toggleTextActive: { color: colors.textPrimary },
  label: { color: colors.textPrimary, fontSize: 13, fontWeight: "600", marginBottom: 6, marginTop: 6 },
  modelList: { gap: 8, marginBottom: 12 },
  modelChip: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 10,
    backgroundColor: colors.card,
    padding: 10,
  },
  modelChipActive: { borderColor: colors.primary, backgroundColor: colors.cardAlt },
  modelChipText: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  modelChipTextActive: { color: colors.textPrimary },
  modelChipPrice: { color: colors.muted, fontSize: 11, marginTop: 2 },
  input: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    color: colors.textPrimary,
    fontSize: 14,
    minHeight: 88,
    textAlignVertical: "top",
    marginBottom: 12,
  },
  sourcePanel: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    marginBottom: 12,
  },
  identityRow: { gap: 8, paddingVertical: 4 },
  identityChip: {
    width: 150,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 10,
    backgroundColor: colors.card,
    padding: 9,
  },
  identityChipActive: { borderColor: colors.success, backgroundColor: colors.cardAlt },
  identityChipText: { color: colors.textPrimary, fontSize: 12, fontWeight: "600" },
  identityDigest: { color: colors.muted, fontSize: 10, marginTop: 3 },
  urlInput: { minHeight: 0, marginBottom: 4 },
  button: {
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingVertical: 12,
    alignItems: "center",
    justifyContent: "center",
  },
  buttonDisabled: { opacity: 0.5 },
  buttonText: { color: colors.bg, fontSize: 15, fontWeight: "600" },
  cancelButton: {
    borderColor: colors.error,
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 12,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 10,
  },
  cancelText: { color: colors.error, fontSize: 15, fontWeight: "600" },
  walletBar: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 10,
    marginBottom: 14,
  },
  walletLabel: { color: colors.muted, fontSize: 13 },
  walletValue: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  walletHeld: { color: colors.muted, fontSize: 12, fontWeight: "400" },
  insufficient: { color: colors.error, fontSize: 13, marginTop: 8 },
  errorRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 12, marginTop: 8 },
  errorText: { flex: 1, marginTop: 0 },
  retryBtn: { backgroundColor: colors.cardAlt, borderColor: colors.border, borderWidth: 1, borderRadius: 10, paddingHorizontal: 14, paddingVertical: 8 },
  retryText: { color: colors.textPrimary, fontSize: 13, fontWeight: "600" },
  historySection: { marginTop: 20 },
  historyTitle: { color: colors.muted, fontSize: 13, fontWeight: "600", marginBottom: 10 },
  historyRow: { gap: 10, paddingRight: 8 },
  historyTile: { width: 110 },
  historyThumb: { width: 110, height: 72, borderRadius: 8, backgroundColor: colors.cardAlt },
  historyIcon: { alignItems: "center", justifyContent: "center" },
  historyIconText: { color: colors.textSecondary, fontSize: 22 },
  historyModel: { color: colors.textPrimary, fontSize: 11, marginTop: 4 },
  historyCost: { color: colors.muted, fontSize: 11 },
  identityStatus: { color: colors.success, fontSize: 10, marginTop: 2 },
  proofCard: {
    backgroundColor: colors.card,
    borderColor: colors.success,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginTop: 16,
  },
  proofHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: 8, marginBottom: 8 },
  proofTitle: { color: colors.success, fontSize: 14, fontWeight: "700" },
  proofButton: { borderColor: colors.border, borderWidth: 1, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 8 },
  proofField: { borderTopColor: colors.border, borderTopWidth: 1, paddingVertical: 7 },
  proofLabel: { color: colors.muted, fontSize: 10 },
  proofValue: { color: colors.textPrimary, fontSize: 11 },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginTop: 16,
  },
  badge: { color: colors.success, fontSize: 13, fontWeight: "600", marginBottom: 8 },
  preview: { width: "100%", height: 320, borderRadius: 10, backgroundColor: colors.cardAlt },
  animateButton: { marginTop: 10 },
  name: { color: colors.textPrimary, fontSize: 15, fontWeight: "600", marginBottom: 4 },
  desc: { color: colors.textSecondary, fontSize: 13, marginTop: 8 },
  meta: { color: colors.muted, fontSize: 12, marginTop: 4 },
  error: { color: colors.error, fontSize: 14, marginTop: 8 },
  loading: { marginTop: 24 },
  statsRow: { flexDirection: "row", gap: 12, marginBottom: 8 },
  stat: {
    flex: 1,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
  },
  statLabel: { color: colors.muted, fontSize: 12, marginBottom: 4 },
  statValue: { color: colors.textPrimary, fontSize: 22, fontWeight: "700" },
  usageRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    marginTop: 8,
  },
  usageLeft: { flex: 1, paddingRight: 8 },
  usageSpend: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  spacer: { height: 24 },
});
