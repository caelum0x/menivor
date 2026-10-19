"use client";

import * as React from "react";
import { AlertCircle, Loader2, Sparkles } from "lucide-react";
import type { UserVoice } from "@/lib/types";
import { cloneVoice, getVoiceVerificationPhrase, presignAndUpload } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Textarea } from "@/components/ui/textarea";
import { useApiToken } from "@/lib/use-api-token";
import {
  AudioSampleInput,
  type AudioSample,
} from "@/components/voices/AudioSampleInput";
import {
  VerificationRecorder,
  type VerificationTake,
} from "@/components/voices/VerificationRecorder";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface CloneVoiceFormProps {
  /** Called with the newly cloned voice so the parent can prepend it. */
  onCreated: (voice: UserVoice) => void;
}

const CONSENT_TEXT =
  "I confirm I own or am authorized to clone this voice.";

const NAME_MAX = 200;

type Phase =
  | { status: "idle" }
  | { status: "uploading"; progress: number }
  | { status: "cloning" }
  | { status: "error"; message: string };

/**
 * Brand Voice creation form: name the voice, record or upload a sample, read
 * the verification phrase live (M7.2), and attest consent (REQUIRED). On submit it presigns + uploads the sample, then
 * calls POST /voices/clone and reports the new voice up. All fields are reset
 * after a successful clone. State is immutable — inputs are controlled.
 */
export function CloneVoiceForm({ onCreated }: CloneVoiceFormProps) {
  const getApiToken = useApiToken();

  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [sample, setSample] = React.useState<AudioSample | null>(null);
  const [consent, setConsent] = React.useState(false);
  const [take, setTake] = React.useState<VerificationTake | null>(null);
  const [recorderKey, setRecorderKey] = React.useState(0);
  const [phase, setPhase] = React.useState<Phase>({ status: "idle" });

  const busy = phase.status === "uploading" || phase.status === "cloning";
  const canSubmit =
    !busy && name.trim().length > 0 && sample !== null && take !== null && consent;

  const loadPhrase = React.useCallback(async () => {
    const token = await getApiToken();
    return getVoiceVerificationPhrase({ token });
  }, [getApiToken]);

  const reset = React.useCallback(() => {
    setName("");
    setDescription("");
    setSample(null);
    setConsent(false);
    setTake(null);
    setRecorderKey((k) => k + 1);
    setPhase({ status: "idle" });
  }, []);

  const handleSubmit = React.useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!sample || !take || !consent || name.trim().length === 0) return;

      setPhase({ status: "uploading", progress: 0 });
      try {
        const token = await getApiToken();
        const { key } = await presignAndUpload(sample.file, {
          token,
          onProgress: (fraction) =>
            setPhase({ status: "uploading", progress: Math.round(fraction * 90) }),
        });
        const { key: verificationKey } = await presignAndUpload(take.file, {
          token,
          onProgress: (fraction) =>
            setPhase({ status: "uploading", progress: 90 + Math.round(fraction * 10) }),
        });

        setPhase({ status: "cloning" });
        const voice = await cloneVoice(
          {
            name: name.trim(),
            sample_key: key,
            consent: true,
            description: description.trim() || undefined,
            verification_token: take.token,
            verification_key: verificationKey,
          },
          { token },
        );

        onCreated(voice);
        reset();
      } catch (err) {
        const message =
          friendlyErrorMessage(err, "Could not create your brand voice. Please try again.");
        setPhase({ status: "error", message });
      }
    },
    [consent, description, getApiToken, name, onCreated, reset, sample, take],
  );

  return (
    <Card>
      <CardContent className="p-6">
        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="space-y-2">
            <Label htmlFor="voice-name">Voice name</Label>
            <Input
              id="voice-name"
              value={name}
              maxLength={NAME_MAX}
              placeholder="e.g. My Brand Voice"
              onChange={(e) => setName(e.target.value)}
              disabled={busy}
              required
            />
          </div>

          <div className="space-y-2">
            <Label>Voice sample</Label>
            <AudioSampleInput
              value={sample}
              onChange={setSample}
              disabled={busy}
            />
          </div>

          <div className="space-y-2">
            <Label>Voice check</Label>
            <VerificationRecorder
              key={recorderKey}
              loadPhrase={loadPhrase}
              value={take}
              onChange={setTake}
              disabled={busy}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="voice-description">
              Description{" "}
              <span className="font-normal text-muted-foreground">
                (optional)
              </span>
            </Label>
            <Textarea
              id="voice-description"
              value={description}
              rows={2}
              maxLength={1000}
              placeholder="A short note to help you recognise this voice later."
              onChange={(e) => setDescription(e.target.value)}
              disabled={busy}
            />
          </div>

          <label className="flex items-start gap-3 rounded-lg border border-border bg-secondary/20 p-3">
            <input
              type="checkbox"
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
              disabled={busy}
              required
              className="mt-0.5 size-4 shrink-0 cursor-pointer accent-primary"
              aria-label={CONSENT_TEXT}
            />
            <span className="text-sm text-foreground">
              {CONSENT_TEXT}
              <span className="mt-1 block text-xs text-muted-foreground">
                Cloning a voice you do not own or have permission to use is not
                allowed. Names of public figures and characters are refused.
              </span>
            </span>
          </label>

          {phase.status === "uploading" && (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">
                Uploading sample… {phase.progress}%
              </p>
              <Progress value={phase.progress} />
            </div>
          )}

          {phase.status === "error" && (
            <p
              role="alert"
              className="flex items-center gap-2 text-sm text-destructive"
            >
              <AlertCircle className="size-4 shrink-0" aria-hidden />
              {phase.message}
            </p>
          )}

          <Button type="submit" disabled={!canSubmit} className="w-full">
            {busy ? (
              <>
                <Loader2 className="animate-spin" />
                {phase.status === "cloning" ? "Cloning voice…" : "Uploading…"}
              </>
            ) : (
              <>
                <Sparkles /> Create brand voice
              </>
            )}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
