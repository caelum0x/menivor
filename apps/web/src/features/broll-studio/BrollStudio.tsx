"use client";

// Feature controller for canonical AI B-roll generation and attachment.

import * as React from "react";
import { useRouter } from "next/navigation";
import { AlertCircle, Check, Copy, Loader2, Sparkles, X } from "lucide-react";
import type { BrollGenMode, BrollGeneration, BrollPreset } from "@/lib/types";
import { JobState, isFailedState, isTerminalState } from "@/lib/types";
import { ApiError, listBrollPresets, uploadAndRegisterImage } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Textarea } from "@/components/ui/textarea";
import { SelfieInput, type SelfiePhoto } from "@/components/avatars/SelfieInput";
import { useApiToken } from "@/lib/use-api-token";
import { useBrollStudio } from "./use-broll-studio";
import { useGenerationCapabilities } from "@/lib/use-generation-capabilities";
import { stashBrollAttachment } from "@/src/shared/media";
import { GenerationUnavailableCta } from "@/components/marketing/GenerationUnavailableCta";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

const PROMPT_MAX = 500;

function brollRuntimeReady(capabilities: unknown): boolean {
  if (!capabilities || typeof capabilities !== "object") return true;
  const product = (capabilities as { product?: unknown }).product;
  if (!product || typeof product !== "object") return true;
  const runtime = (product as { runtime?: unknown }).runtime;
  if (!runtime || typeof runtime !== "object") return true;
  return (runtime as { storage_ready?: unknown }).storage_ready !== false;
}

/**
 * Load the caller's available motion presets once. Best-effort: a failure leaves
 * an empty list so the studio still works with a free-text prompt.
 */
function useBrollPresets(): readonly BrollPreset[] {
  const getApiToken = useApiToken();
  const [presets, setPresets] = React.useState<readonly BrollPreset[]>([]);

  React.useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    void (async () => {
      try {
        const token = await getApiToken();
        const rows = await listBrollPresets({ token, signal: controller.signal });
        if (!cancelled) setPresets(rows);
      } catch (err) {
        if (err instanceof ApiError || err instanceof Error) {
          // Presets are optional — degrade silently to the free-text prompt.
        }
      }
    })();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [getApiToken]);

  return presets;
}

/**
 * AI B-roll Studio body: a prompt box that starts an async text->video
 * generation and a live list of this session's generations, each polling to
 * completion. A completed clip can be attached directly to the new-reel
 * wizard; its durable `broll_key` is retained across the route transition.
 */
export function BrollStudio() {
  const router = useRouter();
  const { generations, status, errorMessage, generate, dismiss } =
    useBrollStudio();
  const getApiToken = useApiToken();
  const capabilityState = useGenerationCapabilities();
  const generationAllowed =
    capabilityState.capabilities?.generation.broll === true &&
    brollRuntimeReady(capabilityState.capabilities);
  const presets = useBrollPresets();
  const [prompt, setPrompt] = React.useState("");
  const [mode, setMode] = React.useState<BrollGenMode>("t2v");
  const [workflowId, setWorkflowId] = React.useState("");
  const [presetId, setPresetId] = React.useState("");
  const [image, setImage] = React.useState<SelfiePhoto | null>(null);
  const [uploading, setUploading] = React.useState(false);
  const [uploadError, setUploadError] = React.useState("");

  const submitting = status === "submitting" || uploading;
  const canSubmit =
    generationAllowed &&
    !submitting &&
    prompt.trim().length > 0 &&
    (mode === "t2v" || image !== null);

  const applyPreset = React.useCallback((preset: BrollPreset) => {
    setPresetId(preset.id);
    setMode(preset.mode);
    setWorkflowId(preset.workflow_id || "");
    if (preset.prompt_template) setPrompt(preset.prompt_template.slice(0, PROMPT_MAX));
  }, []);

  const resetForm = React.useCallback(() => {
    setPrompt("");
    setPresetId("");
    setWorkflowId("");
    setImage(null);
    setMode("t2v");
  }, []);

  const attachToNewReel = React.useCallback(
    (generation: BrollGeneration) => {
      if (!generation.broll_key) return;
      stashBrollAttachment({
        key: generation.broll_key,
        resultUrl: generation.result_url || "",
      });
      router.push("/new");
    },
    [router],
  );

  const handleSubmit = React.useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!generationAllowed) return;
      const trimmed = prompt.trim();
      if (!trimmed) return;
      if (mode === "i2v" && !image) return;
      setUploadError("");
      try {
        // For i2v, upload + register the reference image first, then generate.
        let imageKey: string | undefined;
        if (mode === "i2v" && image) {
          setUploading(true);
          try {
            const token = await getApiToken();
            imageKey = await uploadAndRegisterImage(image.file, { token });
          } finally {
            setUploading(false);
          }
        }
        await generate({
          prompt: trimmed,
          mode,
          ...(imageKey ? { image_key: imageKey } : {}),
          ...(workflowId ? { workflow_id: workflowId } : {}),
        });
        resetForm();
      } catch (err) {
        if (err instanceof ApiError || err instanceof Error) {
          setUploadError(friendlyErrorMessage(err));
        }
        // Generation errors also surface via `errorMessage`; keep inputs for retry.
      }
    },
    [
      prompt,
      mode,
      image,
      workflowId,
      generate,
      getApiToken,
      resetForm,
      generationAllowed,
    ],
  );

  if (capabilityState.loading) {
    return (
      <Card>
        <CardContent className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" aria-hidden />
          Checking B-roll availability…
        </CardContent>
      </Card>
    );
  }

  if (!generationAllowed) {
    return (
      <Card>
        <CardContent className="py-8">
          <p className="font-medium">AI B-roll is not available for this account.</p>
          <p className="mt-2 text-sm text-muted-foreground" role="alert">
            {capabilityState.error ||
              "AI B-roll is not open on the free tier yet."}
          </p>
          <GenerationUnavailableCta />
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,420px)_1fr]">
      <div className="lg:sticky lg:top-6 lg:self-start">
        <Card>
          <CardContent className="pt-6">
            <form onSubmit={handleSubmit} className="space-y-4">
              {presets.length > 0 && (
                <div className="space-y-2">
                  <Label>Start from a motion preset</Label>
                  <div className="flex flex-wrap gap-2">
                    {presets.map((preset) => (
                      <button
                        key={preset.id}
                        type="button"
                        onClick={() => applyPreset(preset)}
                        disabled={submitting}
                        title={preset.description}
                        aria-pressed={presetId === preset.id}
                        className={
                          presetId === preset.id
                            ? "rounded-full border border-primary bg-primary/10 px-3 py-1 text-xs font-medium text-primary"
                            : "rounded-full border border-border px-3 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted"
                        }
                      >
                        {preset.name}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <div className="space-y-2">
                <Label htmlFor="broll-prompt">Describe the motion clip</Label>
                <Textarea
                  id="broll-prompt"
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value.slice(0, PROMPT_MAX))}
                  placeholder="Slow aerial push over a neon Tokyo street at night, rain-slick pavement reflecting the signs"
                  rows={5}
                  disabled={submitting}
                  aria-describedby="broll-prompt-hint"
                />
                <p
                  id="broll-prompt-hint"
                  className="flex items-center justify-between text-xs text-muted-foreground"
                >
                  <span>Text → 5s vertical motion clip.</span>
                  <span>
                    {prompt.length}/{PROMPT_MAX}
                  </span>
                </p>
              </div>

              {mode === "i2v" && (
                <div className="space-y-2">
                  <Label>Reference image</Label>
                  <SelfieInput
                    value={image}
                    onChange={setImage}
                    disabled={submitting}
                  />
                  <p className="text-xs text-muted-foreground">
                    Your image animates into a 5s motion clip. Only upload an
                    image you own or are authorized to use.
                  </p>
                </div>
              )}

              {(uploadError || (status === "error" && errorMessage)) && (
                <p
                  className="flex items-start gap-2 text-sm text-destructive"
                  role="alert"
                >
                  <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
                  {uploadError || errorMessage}
                </p>
              )}

              <Button type="submit" disabled={!canSubmit} className="w-full">
                {submitting ? (
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                ) : (
                  <Sparkles className="size-4" aria-hidden />
                )}
                Generate clip
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>

      <div>
        <h2 className="mb-4 text-lg font-semibold tracking-tight">
          This session
          {generations.length > 0 && (
            <span className="ml-2 text-sm font-normal text-muted-foreground">
              {generations.length}
            </span>
          )}
        </h2>

        {generations.length === 0 ? (
          <Card>
            <CardContent className="py-12 text-center text-sm text-muted-foreground">
              Your generated clips appear here. Each takes ~30–120s on a GPU.
            </CardContent>
          </Card>
        ) : (
          <ul className="space-y-3">
            {generations.map((gen) => (
              <li key={gen.generation_id}>
                <GenerationRow
                  gen={gen}
                  onDismiss={dismiss}
                  onAttach={attachToNewReel}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

interface GenerationRowProps {
  gen: BrollGeneration;
  onDismiss: (id: string) => void;
  onAttach: (generation: BrollGeneration) => void;
}

function GenerationRow({ gen, onDismiss, onAttach }: GenerationRowProps) {
  const terminal = isTerminalState(gen.state);
  const failed = isFailedState(gen.state);
  const complete = gen.state === JobState.Complete;

  return (
    <Card>
      <CardContent className="flex items-center gap-4 py-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <StatusPill gen={gen} />
            <span className="truncate font-mono text-xs text-muted-foreground">
              {gen.generation_id}
            </span>
          </div>
          {!terminal && (
            <Progress
              value={gen.progress}
              className="mt-3 h-1.5"
              aria-label="Generation progress"
            />
          )}
          {complete && gen.broll_key && (
            <>
              {gen.result_url && (
                <video
                  className="mt-3 aspect-[9/16] max-h-72 rounded-md bg-black"
                  controls
                  preload="metadata"
                  src={gen.result_url}
                  aria-label="Generated B-roll preview"
                />
              )}
              <Button
                type="button"
                className="mt-3"
                onClick={() => onAttach(gen)}
              >
                Attach to new reel
              </Button>
              <CopyKey broll_key={gen.broll_key} />
            </>
          )}
        </div>

        {terminal && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onDismiss(gen.generation_id)}
            aria-label="Dismiss"
          >
            <X className="size-4" aria-hidden />
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

function StatusPill({ gen }: { gen: BrollGeneration }) {
  if (gen.state === JobState.Complete) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-600">
        <Check className="size-3" aria-hidden /> Ready
      </span>
    );
  }
  if (isFailedState(gen.state)) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-destructive/10 px-2 py-0.5 text-xs font-medium text-destructive">
        <AlertCircle className="size-3" aria-hidden /> Failed
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
      <Loader2 className="size-3 animate-spin" aria-hidden /> Generating
    </span>
  );
}

function CopyKey({ broll_key }: { broll_key: string }) {
  const [copied, setCopied] = React.useState(false);

  const copy = React.useCallback(async () => {
    try {
      await navigator.clipboard.writeText(broll_key);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard denied (insecure context / permissions): leave state as-is.
    }
  }, [broll_key]);

  return (
    <button
      type="button"
      onClick={copy}
      className="mt-2 flex w-full items-center gap-2 rounded-md border border-border bg-muted/40 px-2 py-1.5 text-left text-xs transition-colors hover:bg-muted"
      title="Copy the clip's R2 key to use as a reel's intro/outro B-roll"
    >
      {copied ? (
        <Check className="size-3.5 shrink-0 text-emerald-600" aria-hidden />
      ) : (
        <Copy className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
      )}
      <span className="truncate font-mono">{broll_key}</span>
    </button>
  );
}
