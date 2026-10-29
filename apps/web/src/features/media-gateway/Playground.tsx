"use client";

import * as React from "react";
import Link from "next/link";
import { useAuth } from "@/components/auth/clerk-safe";
import { Coins, Download, FileJson, ImageIcon, Loader2, Music, Play, RotateCcw, ShieldCheck, Sparkles, Video } from "lucide-react";

import { ApiError, POLL_INTERVAL_MS } from "@/src/shared/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  createAudio,
  createImage,
  createVideo,
  estimateCostMicros,
  formatUsdMicros,
  getAudio,
  getGeneration,
  getGenerationProvenance,
  getVideo,
  listGenerations,
  listIdentityOptions,
  listMediaModels,
  priceLabel,
  settlementProofView,
  type MediaModel,
  type Modality,
  type IdentityOption,
} from "./api";
import { useCredits } from "./use-credits";
import { GenerationHistory, type HistoryEntry } from "./GenerationHistory";
import { downloadJson, downloadUrl, generationFilename } from "./download";
import { pollUntilTerminal } from "./poll";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { ShareActions } from "@/src/features/share-actions/ShareActions";

const isTerminal = (v: { status: string }) => v.status === "completed" || v.status === "failed";

/** One key + one balance → generate an image (sync) or a video (submit + poll). */
export function Playground() {
  const { getToken } = useAuth();
  const { credits, loading: creditsLoading, refresh: refreshCredits } = useCredits();
  const [modality, setModality] = React.useState<Modality>("image");
  const [models, setModels] = React.useState<MediaModel[]>([]);
  const [model, setModel] = React.useState("");
  const [prompt, setPrompt] = React.useState("");
  const [duration, setDuration] = React.useState(5);
  const [referenceImageUrl, setReferenceImageUrl] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [imageUrl, setImageUrl] = React.useState("");
  const [videoStatus, setVideoStatus] = React.useState("");
  const [videoUrl, setVideoUrl] = React.useState("");
  const [audioUrl, setAudioUrl] = React.useState("");
  const [cost, setCost] = React.useState<number | null>(null);
  const [resultId, setResultId] = React.useState("");
  const [resultKind, setResultKind] = React.useState<"image" | "video">("image");
  const [history, setHistory] = React.useState<HistoryEntry[]>([]);
  const [identities, setIdentities] = React.useState<IdentityOption[]>([]);
  const [identityKey, setIdentityKey] = React.useState("");
  const [inspectedEntry, setInspectedEntry] = React.useState<HistoryEntry | null>(null);
  const [exportingProof, setExportingProof] = React.useState(false);
  const preferImageToVideo = React.useRef(false);
  const settlementProof = inspectedEntry ? settlementProofView(inspectedEntry) : null;

  const refreshHistory = React.useCallback(async () => {
    try {
      const token = (await getToken()) ?? undefined;
      const page = await listGenerations(
        { limit: 24, refreshPending: true },
        { token },
      );
      setHistory(page.generations);
    } catch {
      // Generation controls remain usable if history recovery is unavailable.
    }
  }, [getToken]);

  // Re-open a past result in the main preview without regenerating.
  const openEntry = React.useCallback(async (entry: HistoryEntry) => {
    setError("");
    setVideoStatus("");
    let current = entry;
    if (!entry.is_terminal) {
      try {
        current = await getGeneration(entry.id, {
          token: (await getToken()) ?? undefined,
        });
        setHistory((items) => items.map((item) => item.id === current.id ? current : item));
      } catch (err) {
        setError(friendlyErrorMessage(err, "Resume failed."));
      }
    }
    setInspectedEntry(current);
    if (current.modality === "image" || current.modality === "video") {
      setResultId(current.id);
      setResultKind(current.modality);
    }
    setImageUrl(current.modality === "image" ? current.output_url || "" : "");
    setVideoUrl(current.modality === "video" ? current.output_url || "" : "");
    setAudioUrl(current.modality === "audio" ? current.output_url || "" : "");
    setCost(current.effective_cost_micros);
    setModality(current.modality);
  }, [getToken]);

  React.useEffect(() => {
    void refreshHistory();
  }, [refreshHistory]);

  // Load the model list for the selected modality; default the picker.
  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const token = (await getToken()) ?? undefined;
        const { models: rows } = await listMediaModels(modality, { token });
        if (cancelled) return;
        setModels(rows);
        setModel((prev) => {
          if (rows.some((m) => m.id === prev)) return prev;
          if (modality === "video" && preferImageToVideo.current) {
            preferImageToVideo.current = false;
            return rows.find((m) => m.id.toLowerCase().includes("i2v"))?.id || rows[0]?.id || "";
          }
          return rows[0]?.id || "";
        });
      } catch {
        if (!cancelled) setModels([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [modality, getToken]);

  React.useEffect(() => {
    if (modality !== "video") return;
    let cancelled = false;
    (async () => {
      try {
        const token = (await getToken()) ?? undefined;
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
  }, [modality, getToken]);

  const reset = () => {
    setError("");
    setImageUrl("");
    setVideoUrl("");
    setAudioUrl("");
    setVideoStatus("");
    setCost(null);
    setResultId("");
  };

  const onGenerateImage = React.useCallback(async () => {
    reset();
    setBusy(true);
    try {
      const token = (await getToken()) ?? undefined;
      const result = await createImage({ model, prompt: prompt.trim() }, { token });
      setImageUrl(result.url);
      setResultId(result.id);
      setResultKind("image");
      setCost(result.cost_micros);
      void refreshCredits(); // reflect the debit
    } catch (err) {
      setError(friendlyErrorMessage(err, "Failed."));
    } finally {
      void refreshHistory();
      setBusy(false);
    }
  }, [model, prompt, getToken, refreshCredits, refreshHistory]);

  const onGenerateVideo = React.useCallback(async () => {
    reset();
    setBusy(true);
    try {
      const token = (await getToken()) ?? undefined;
      const job = await createVideo(
        {
          model,
          prompt: prompt.trim(),
          duration,
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
      setVideoStatus(job.status);
      setCost(job.cost_micros);
      // Poll to terminal, bounded by MAX_POLL_MS.
      const { value: current, timedOut } = await pollUntilTerminal(
        async () => getVideo(job.id, { token: (await getToken()) ?? undefined }),
        isTerminal,
        { intervalMs: POLL_INTERVAL_MS, onTick: (v) => setVideoStatus(v.status) },
      );
      if (timedOut) {
        setError("Still processing — it'll appear in your jobs when ready.");
      } else if (current.status === "completed") {
        setVideoUrl(current.url);
        setResultId(job.id);
        setResultKind("video");
        setCost(current.cost_micros);
      } else {
        setError(current.error || "Generation failed.");
      }
      void refreshCredits(); // settle (debit on success, release on failure)
    } catch (err) {
      setError(friendlyErrorMessage(err, "Failed."));
    } finally {
      void refreshHistory();
      setBusy(false);
    }
  }, [model, prompt, duration, referenceImageUrl, identities, identityKey, getToken, refreshCredits, refreshHistory]);

  const exportProvenance = React.useCallback(async () => {
    if (!inspectedEntry?.identity) return;
    setExportingProof(true);
    setError("");
    try {
      const token = (await getToken()) ?? undefined;
      const proof = await getGenerationProvenance(inspectedEntry.id, { token });
      downloadJson(proof, `menivor-provenance-${inspectedEntry.id}.json`);
    } catch (err) {
      setError(friendlyErrorMessage(err, "Proof export failed."));
    } finally {
      setExportingProof(false);
    }
  }, [getToken, inspectedEntry]);

  const onGenerateAudio = React.useCallback(async () => {
    reset();
    setBusy(true);
    try {
      const token = (await getToken()) ?? undefined;
      const job = await createAudio({ model, prompt: prompt.trim() }, { token });
      setVideoStatus(job.status);
      setCost(job.cost_micros);
      const { value: current, timedOut } = await pollUntilTerminal(
        async () => getAudio(job.id, { token: (await getToken()) ?? undefined }),
        isTerminal,
        { intervalMs: POLL_INTERVAL_MS, onTick: (v) => setVideoStatus(v.status) },
      );
      if (timedOut) {
        setError("Still processing — it'll appear in your jobs when ready.");
      } else if (current.status === "completed") {
        setAudioUrl(current.url);
        setCost(current.cost_micros);
      } else {
        setError(current.error || "Generation failed.");
      }
      void refreshCredits(); // settle (debit on success, release on failure)
    } catch (err) {
      setError(friendlyErrorMessage(err, "Failed."));
    } finally {
      void refreshHistory();
      setBusy(false);
    }
  }, [model, prompt, getToken, refreshCredits, refreshHistory]);

  const onGenerate =
    modality === "image" ? onGenerateImage : modality === "video" ? onGenerateVideo : onGenerateAudio;

  const selected = models.find((m) => m.id === model);
  const imageRequired = modality === "video" && selected?.id.toLowerCase().includes("i2v");
  const estimate = estimateCostMicros(selected, modality, duration);
  const available = credits?.available_micros ?? 0;
  // Only guard once the balance has actually loaded (avoid a false "insufficient"
  // flash on first paint). Video/audio hold the estimate up-front; image debits on
  // success — the pre-flight is the same reserve check the server runs.
  const affordable = creditsLoading || credits === null || estimate <= available;
  const canRun =
    model !== "" &&
    prompt.trim() !== "" &&
    (!imageRequired || referenceImageUrl.trim() !== "") &&
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
    <div className="space-y-4">
      <div className="flex items-center justify-between rounded-lg border px-3 py-2">
        <span className="flex items-center gap-2 text-sm text-muted-foreground">
          <Coins className="h-4 w-4" /> Wallet balance
        </span>
        <span className="text-sm font-semibold" aria-live="polite">
          {creditsLoading && credits === null
            ? "…"
            : credits
              ? formatUsdMicros(available)
              : "—"}
          {credits && credits.reserved_micros > 0 ? (
            <span className="ml-2 text-xs font-normal text-muted-foreground">
              ({formatUsdMicros(credits.reserved_micros)} held)
            </span>
          ) : null}
        </span>
      </div>

      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant={modality === "image" ? "default" : "outline"}
          onClick={() => setModality("image")}
        >
          <ImageIcon className="mr-1 h-4 w-4" /> Image
        </Button>
        <Button
          size="sm"
          variant={modality === "video" ? "default" : "outline"}
          onClick={() => setModality("video")}
        >
          <Video className="mr-1 h-4 w-4" /> Video
        </Button>
        <Button
          size="sm"
          variant={modality === "audio" ? "default" : "outline"}
          onClick={() => setModality("audio")}
        >
          <Music className="mr-1 h-4 w-4" /> Audio
        </Button>
      </div>

      <Card>
        <CardContent className="space-y-3 py-4">
          <label className="block text-sm font-medium">Model</label>
          <select
            className="w-full rounded-md border bg-transparent px-3 py-2 text-sm"
            value={model}
            onChange={(e) => setModel(e.target.value)}
          >
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.id} — {priceLabel(m)}
              </option>
            ))}
          </select>

          <label className="block text-sm font-medium">Prompt</label>
          <Textarea
            rows={3}
            placeholder="A red panda surfing a neon wave, cinematic"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
          />

          {modality === "video" ? (
            <div className="space-y-3 rounded-md border bg-muted/20 p-3">
              <div className="flex items-center gap-2">
                <label className="text-sm font-medium">Duration (s)</label>
                <Input
                  type="number"
                  min={1}
                  max={selected?.max_seconds || 10}
                  value={duration}
                  onChange={(e) => setDuration(Number(e.target.value) || 1)}
                  className="w-24"
                />
              </div>
              <div className="space-y-1.5">
                <label className="block text-sm font-medium" htmlFor="media-reference-image">
                  Source image {imageRequired ? "(required)" : "(optional)"}
                </label>
                <Input
                  id="media-reference-image"
                  type="url"
                  placeholder="https://…"
                  value={referenceImageUrl}
                  onChange={(event) => setReferenceImageUrl(event.target.value)}
                  aria-describedby="media-reference-help"
                />
                <p id="media-reference-help" className="text-xs text-muted-foreground">
                  Use a generated image or paste a public image URL to create an image-to-video shot.
                </p>
              </div>
              <div className="space-y-1.5">
                <label className="block text-sm font-medium" htmlFor="media-identity-lock">
                  Identity Lock (optional)
                </label>
                <select
                  id="media-identity-lock"
                  className="w-full rounded-md border bg-transparent px-3 py-2 text-sm"
                  value={identityKey}
                  onChange={(event) => setIdentityKey(event.target.value)}
                >
                  <option value="">No locked passport</option>
                  {identities.map((identity) => (
                    <option
                      key={`${identity.passport_id}:${identity.version}`}
                      value={`${identity.passport_id}:${identity.version}`}
                    >
                      {identity.kind} · {identity.passport_id} · v{identity.version}
                    </option>
                  ))}
                </select>
                <p className="text-xs text-muted-foreground">
                  The exact locked version and digest are resolved before the provider runs. Currently available for video models with portable reference-image conditioning.
                </p>
              </div>
            </div>
          ) : null}

          <div className="flex items-center justify-between pt-1">
            <div className="text-xs text-muted-foreground">
              {selected ? (
                <>
                  Est. <span className="font-medium text-foreground">{formatUsdMicros(estimate)}</span>
                  {modality === "video" ? ` for ${duration}s` : ""}
                </>
              ) : (
                "Select a model"
              )}
            </div>
            <Button disabled={!canRun} onClick={onGenerate}>
              {busy ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="mr-1 h-4 w-4" />
              )}
              Generate
            </Button>
          </div>

          {selected && credits !== null && !creditsLoading && estimate > available ? (
            <div className="flex items-center justify-between rounded-md bg-red-50 px-3 py-2 text-xs text-red-700 dark:bg-red-950/40 dark:text-red-400">
              <span>
                Insufficient balance — need {formatUsdMicros(estimate)}, have {formatUsdMicros(available)}.
              </span>
              <Link href="/billing" className="font-medium underline">
                Top up
              </Link>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {error ? (
        <Card>
          <CardContent className="flex items-center justify-between gap-3 py-4">
            <span className="text-sm text-red-600">{error}</span>
            <Button size="sm" variant="outline" onClick={onGenerate} disabled={!canRun}>
              <RotateCcw className="mr-1 h-4 w-4" /> Try again
            </Button>
          </CardContent>
        </Card>
      ) : null}

      {videoStatus && !videoUrl && !audioUrl && !error ? (
        <Card>
          <CardContent className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span>Status: {videoStatus}</span>
            {cost !== null ? <Badge variant="outline">held {formatUsdMicros(cost)}</Badge> : null}
          </CardContent>
        </Card>
      ) : null}

      {audioUrl ? (
        <Card>
          <CardContent className="space-y-2 py-4">
            <ResultActions cost={cost} onDownload={() => downloadUrl(audioUrl, generationFilename("audio", model))} />
            <audio src={audioUrl} controls className="w-full" />
          </CardContent>
        </Card>
      ) : null}

      {imageUrl ? (
        <Card>
          <CardContent className="space-y-2 py-4">
            <ResultActions
              cost={cost}
              onDownload={() => downloadUrl(imageUrl, generationFilename("image", model))}
              onAnimate={() => animateImage(imageUrl)}
              scheduler={resultId && resultKind === "image" ? { sourceId: resultId, kind: "image" } : undefined}
            />
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={imageUrl} alt="Generated" className="max-h-[70vh] w-auto rounded-lg" />
          </CardContent>
        </Card>
      ) : null}

      {videoUrl ? (
        <Card>
          <CardContent className="space-y-2 py-4">
            <ResultActions
              cost={cost}
              onDownload={() => downloadUrl(videoUrl, generationFilename("video", model))}
              scheduler={resultId && resultKind === "video" ? { sourceId: resultId, kind: "video" } : undefined}
            />
            <video src={videoUrl} controls className="max-h-[70vh] w-auto rounded-lg" />
          </CardContent>
        </Card>
      ) : null}

      {inspectedEntry && settlementProof ? (
        <Card>
          <CardContent className="space-y-3 py-4">
            <div>
              <p className="text-sm font-medium">Settlement proof</p>
              <p className="text-xs text-muted-foreground">{settlementProof.proofLabel}</p>
            </div>
            <dl className="grid gap-2 text-xs sm:grid-cols-2">
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
            </dl>
          </CardContent>
        </Card>
      ) : null}

      {inspectedEntry?.identity ? (
        <Card>
          <CardContent className="space-y-3 py-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <ShieldCheck className="h-5 w-5 text-emerald-600" />
                <div>
                  <p className="text-sm font-medium">Signed provenance</p>
                  <p className="text-xs text-muted-foreground">
                    {inspectedEntry.identity.status} · passport v{inspectedEntry.identity.version}
                  </p>
                </div>
              </div>
              <Button
                size="sm"
                variant="outline"
                disabled={exportingProof}
                onClick={() => void exportProvenance()}
              >
                {exportingProof ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <FileJson className="mr-1 h-4 w-4" />}
                Export JSON
              </Button>
            </div>
            <dl className="grid gap-2 text-xs sm:grid-cols-2">
              <ProofField label="Passport" value={inspectedEntry.identity.passport_id} />
              <ProofField label="Digest" value={inspectedEntry.identity.content_digest} />
              <ProofField label="Output" value={inspectedEntry.output_url || "pending"} />
              <ProofField label="Payer" value={inspectedEntry.identity.payer_account || "pending"} />
              <ProofField label="Request" value={inspectedEntry.identity.request_id || "pending"} />
              <ProofField label="Provenance ID" value={inspectedEntry.identity.provenance_id || "pending"} />
              <ProofField label="Receipt hash" value={inspectedEntry.identity.receipt?.receipt_hash || "pending"} />
              <ProofField label="Signature" value={inspectedEntry.identity.receipt?.signature || "pending"} />
            </dl>
          </CardContent>
        </Card>
      ) : null}

      <GenerationHistory items={history} onSelect={openEntry} />
    </div>
  );
}

function ProofField({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded border bg-muted/20 p-2">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="truncate font-mono" title={value}>{value}</dd>
    </div>
  );
}

/** Cost badge + a Save/Download action for a generated result. */
function ResultActions({
  cost,
  onDownload,
  onAnimate,
  scheduler,
}: {
  cost: number | null;
  onDownload: () => void;
  onAnimate?: () => void;
  scheduler?: { sourceId: string; kind: "image" | "video" };
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      {cost !== null ? <Badge variant="secondary">{formatUsdMicros(cost)}</Badge> : <span />}
      <div className="flex flex-wrap items-center gap-2">
        {onAnimate ? (
          <Button size="sm" onClick={onAnimate}>
            <Play className="mr-1 h-4 w-4" /> Animate image
          </Button>
        ) : null}
        <Button size="sm" variant="outline" onClick={onDownload}>
          <Download className="mr-1 h-4 w-4" /> Save
        </Button>
        {scheduler ? <ShareActions source="media" sourceId={scheduler.sourceId} kind={scheduler.kind} /> : null}
      </div>
    </div>
  );
}
