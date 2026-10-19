"use client";

import * as React from "react";
import Link from "next/link";
import { Clapperboard, ExternalLink, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { listAvatars, listVoices } from "@/lib/api";
import type { Avatar, Voice } from "@/lib/types";
import { ChipToggle, ErrorText, errorMessage, toggleIn, useRequestOptions } from "@/src/features/ad-studio/shared";
import {
  AD_MODES,
  FREE_VOICES,
  buildAdRequests,
  submitReel,
  type AdMode,
  type CaptureDetail,
  type CaptureFormat,
} from "./api";

interface Made {
  aspect: CaptureFormat;
  jobId?: string;
  error?: string;
}

/** Script + ad mode -> reel jobs built on the capture (one per chosen format). */
export function MakeAdsPanel({ capture }: { capture: CaptureDetail }) {
  const requestOptions = useRequestOptions();
  const available = capture.outputs.map((o) => o.aspect);
  const [mode, setMode] = React.useState<AdMode>("captions");
  const [aspects, setAspects] = React.useState<CaptureFormat[]>(available);
  const [script, setScript] = React.useState(capture.script_draft?.script ?? "");
  const [language, setLanguage] = React.useState<"en" | "tr">("en");
  const [voiceName, setVoiceName] = React.useState(FREE_VOICES[0]?.id ?? "");
  const [avatars, setAvatars] = React.useState<Avatar[] | null>(null);
  const [voices, setVoices] = React.useState<Voice[]>([]);
  const [avatarId, setAvatarId] = React.useState("");
  const [voiceId, setVoiceId] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [made, setMade] = React.useState<Made[]>([]);
  const attempt = React.useRef(0);

  React.useEffect(() => {
    if (mode !== "avatar" || avatars !== null) return;
    let cancelled = false;
    (async () => {
      try {
        const opts = await requestOptions();
        const [a, v] = await Promise.all([listAvatars(opts), listVoices(opts).catch(() => [] as Voice[])]);
        if (cancelled) return;
        setAvatars(a);
        setVoices(v);
        const first = a[0];
        if (first) setAvatarId((cur) => cur || first.avatar_id);
      } catch (err) {
        if (!cancelled) {
          setAvatars([]);
          setError(errorMessage(err));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [mode, avatars, requestOptions]);

  const submit = async () => {
    setError("");
    setMade([]);
    if (!script.trim()) {
      setError("Write a script first.");
      return;
    }
    if (aspects.length === 0) {
      setError("Pick at least one format.");
      return;
    }
    if (mode === "avatar" && !avatarId) {
      setError("Pick an avatar.");
      return;
    }
    setBusy(true);
    attempt.current += 1;
    try {
      const opts = await requestOptions();
      const built = await buildAdRequests(
        capture.id,
        {
          mode,
          aspects,
          script,
          language,
          ...(mode === "voiceover" ? { voice_name: voiceName } : {}),
          ...(mode === "avatar" ? { avatar_id: avatarId, voice_id: voiceId || undefined } : {}),
        },
        opts,
      );
      const results: Made[] = [];
      for (const req of built.requests) {
        try {
          const key = `capture-${capture.id}-${req.aspect}-${mode}-${attempt.current}`;
          const job = await submitReel(req.job_request, key, opts);
          results.push({ aspect: req.aspect, jobId: job.job_id });
        } catch (err) {
          results.push({ aspect: req.aspect, error: errorMessage(err) });
        }
        setMade([...results]);
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardContent className="space-y-5 p-5">
        <div>
          <h2 className="text-lg font-semibold">Make ads</h2>
          <p className="text-sm text-muted-foreground">
            Each format becomes a reel built on this capture. Hooks, captions, voice, auto-publish and the winner
            loop work the same way as for any other reel.
          </p>
        </div>

        <div className="grid gap-3 sm:grid-cols-3" role="radiogroup" aria-label="Ad type">
          {AD_MODES.map((m) => (
            <button
              key={m.id}
              type="button"
              role="radio"
              aria-checked={mode === m.id}
              onClick={() => setMode(m.id)}
              className={`rounded-lg border p-3 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                mode === m.id ? "border-primary bg-primary/10" : "hover:bg-secondary/40"
              }`}
            >
              <span className="block font-medium">{m.label}</span>
              <span className="mt-1 block text-xs text-muted-foreground">{m.detail}</span>
            </button>
          ))}
        </div>

        <div className="space-y-2">
          <span className="text-sm font-medium">Formats</span>
          <div className="flex flex-wrap gap-2" role="group" aria-label="Ad formats">
            {available.map((a) => (
              <ChipToggle key={a} selected={aspects.includes(a)} onToggle={() => setAspects((cur) => toggleIn(cur, a))}>
                {a}
              </ChipToggle>
            ))}
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="ad-script">Script</Label>
          <Textarea
            id="ad-script"
            rows={6}
            maxLength={1200}
            value={script}
            onChange={(e) => setScript(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            Drafted from what the capture found on the page or listing. The first line is the hook. Edit it freely.
          </p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="ad-language">Language</Label>
            <Select id="ad-language" value={language} onChange={(e) => setLanguage(e.target.value as "en" | "tr")}>
              <option value="en">English</option>
              <option value="tr">Turkish</option>
            </Select>
          </div>
          {mode === "voiceover" ? (
            <div className="space-y-2">
              <Label htmlFor="ad-voice">Narration voice</Label>
              <Select id="ad-voice" value={voiceName} onChange={(e) => setVoiceName(e.target.value)}>
                {FREE_VOICES.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label}
                  </option>
                ))}
              </Select>
            </div>
          ) : null}
          {mode === "avatar" ? (
            <>
              <div className="space-y-2">
                <Label htmlFor="ad-avatar">Avatar</Label>
                {avatars === null ? (
                  <p className="text-sm text-muted-foreground">Loading avatars...</p>
                ) : avatars.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No avatars available. <Link href="/avatars" className="underline">Set one up</Link>.
                  </p>
                ) : (
                  <Select id="ad-avatar" value={avatarId} onChange={(e) => setAvatarId(e.target.value)}>
                    {avatars.map((a) => (
                      <option key={a.avatar_id} value={a.avatar_id}>
                        {a.display_name || a.name || a.avatar_id}
                      </option>
                    ))}
                  </Select>
                )}
              </div>
              {voices.length > 0 ? (
                <div className="space-y-2">
                  <Label htmlFor="ad-avatar-voice">Voice</Label>
                  <Select id="ad-avatar-voice" value={voiceId} onChange={(e) => setVoiceId(e.target.value)}>
                    <option value="">Avatar default</option>
                    {voices.map((v) => (
                      <option key={v.voice_id} value={v.voice_id}>
                        {v.name || v.voice_id}
                      </option>
                    ))}
                  </Select>
                </div>
              ) : null}
            </>
          ) : null}
        </div>

        <ErrorText message={error} />
        <Button type="button" onClick={submit} disabled={busy}>
          {busy ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <Clapperboard className="mr-2 h-4 w-4" aria-hidden />
          )}
          Make {aspects.length === 1 ? "1 ad" : `${aspects.length} ads`}
        </Button>

        {made.length > 0 ? (
          <ul className="space-y-2" aria-live="polite">
            {made.map((m) => (
              <li key={m.aspect} className="flex items-center justify-between rounded-md border px-3 py-2 text-sm">
                <span className="font-medium">{m.aspect}</span>
                {m.jobId ? (
                  <Link href={`/jobs/${encodeURIComponent(m.jobId)}`} className="inline-flex items-center gap-1 underline">
                    Open reel <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                  </Link>
                ) : (
                  <span className="text-destructive">{m.error}</span>
                )}
              </li>
            ))}
          </ul>
        ) : null}
      </CardContent>
    </Card>
  );
}
