"use client";

import * as React from "react";
import { Clapperboard, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { listAvatars, listVoices } from "@/lib/api";
import type { Avatar, Voice } from "@/lib/types";
import { AD_ASPECTS, AD_FORMATS, type AdAngle, type AdAspect, type AdFormat, type VariantsInput } from "./api";
import { ChipToggle, ErrorText, errorMessage, toggleIn, useRequestOptions } from "./shared";

const MAX_BATCH = 30;

/** Pick angles x formats x aspects (+ avatar for UGC) and queue the batch. */
export function BatchBuilder({
  angles,
  hasImages,
  onSubmit,
}: {
  angles: AdAngle[];
  hasImages: boolean;
  onSubmit: (input: VariantsInput) => Promise<void>;
}) {
  const requestOptions = useRequestOptions();
  const [angleIds, setAngleIds] = React.useState<string[]>(() => angles.slice(0, 3).map((a) => a.id));
  const [formats, setFormats] = React.useState<AdFormat[]>(["showcase"]);
  const [aspects, setAspects] = React.useState<AdAspect[]>(["9:16"]);
  const [avatars, setAvatars] = React.useState<Avatar[] | null>(null);
  const [voices, setVoices] = React.useState<Voice[]>([]);
  const [avatarId, setAvatarId] = React.useState("");
  const [voiceId, setVoiceId] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const wantsAvatar = formats.includes("ugc_avatar");

  React.useEffect(() => {
    if (!wantsAvatar || avatars !== null) return;
    let cancelled = false;
    (async () => {
      try {
        const opts = await requestOptions();
        const [a, v] = await Promise.all([listAvatars(opts), listVoices(opts).catch(() => [] as Voice[])]);
        if (cancelled) return;
        setAvatars(a);
        setVoices(v);
        const first = a[0];
        if (first) setAvatarId((current) => current || first.avatar_id);
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
  }, [wantsAvatar, avatars, requestOptions]);

  const total = angleIds.length * formats.length * aspects.length;
  const invalid =
    !hasImages || total === 0 || total > MAX_BATCH || (wantsAvatar && !avatarId);

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      await onSubmit({
        angle_ids: angleIds,
        formats,
        aspects,
        ...(wantsAvatar ? { avatar_id: avatarId, voice_id: voiceId || undefined } : {}),
      });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardContent className="space-y-4 p-5">
        <div>
          <p className="mb-2 text-sm font-medium">Angles</p>
          <div className="flex flex-wrap gap-2">
            {angles.map((a) => (
              <ChipToggle key={a.id} selected={angleIds.includes(a.id)} onToggle={() => setAngleIds(toggleIn(angleIds, a.id))} title={a.hook}>
                {a.label}
              </ChipToggle>
            ))}
          </div>
        </div>
        <div>
          <p className="mb-2 text-sm font-medium">Formats</p>
          <div className="grid gap-2 md:grid-cols-3">
            {AD_FORMATS.map((f) => (
              <label
                key={f.id}
                className="flex cursor-pointer gap-2 rounded-md border border-border p-3 text-sm has-[:checked]:border-primary has-[:checked]:bg-primary/10"
              >
                <input type="checkbox" checked={formats.includes(f.id)} onChange={() => setFormats(toggleIn(formats, f.id))} />
                <span>
                  <span className="font-medium">{f.label}</span>
                  <span className="block text-xs text-muted-foreground">{f.detail}</span>
                </span>
              </label>
            ))}
          </div>
        </div>
        <div>
          <p className="mb-2 text-sm font-medium">Aspect ratios</p>
          <div className="flex flex-wrap gap-2">
            {AD_ASPECTS.map((r) => (
              <ChipToggle key={r.id} selected={aspects.includes(r.id)} onToggle={() => setAspects(toggleIn(aspects, r.id))}>
                {r.label}
              </ChipToggle>
            ))}
          </div>
        </div>
        {wantsAvatar ? (
          <div className="grid gap-3 md:grid-cols-2">
            <div className="grid gap-1">
              <Label htmlFor="ad-avatar">Avatar</Label>
              <Select id="ad-avatar" value={avatarId} onChange={(e) => setAvatarId(e.target.value)} disabled={avatars === null}>
                {avatars === null ? <option value="">Loading avatars...</option> : null}
                {avatars?.length === 0 ? <option value="">No avatars available</option> : null}
                {avatars?.map((a) => (
                  <option key={a.avatar_id} value={a.avatar_id}>
                    {a.display_name || a.name || a.avatar_id}
                  </option>
                ))}
              </Select>
            </div>
            <div className="grid gap-1">
              <Label htmlFor="ad-voice">Voice</Label>
              <Select id="ad-voice" value={voiceId} onChange={(e) => setVoiceId(e.target.value)}>
                <option value="">Avatar default voice</option>
                {voices.map((v) => (
                  <option key={v.voice_id} value={v.voice_id}>
                    {v.name || v.voice_id}
                  </option>
                ))}
              </Select>
            </div>
          </div>
        ) : null}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground">
            {total} ad{total === 1 ? "" : "s"} in this batch
            {total > MAX_BATCH ? ` (max ${MAX_BATCH})` : ""}
            {!hasImages ? " · this project has no product images to render" : ""}
          </p>
          <Button onClick={submit} disabled={busy || invalid}>
            {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Clapperboard aria-hidden />}
            Render {total} ad{total === 1 ? "" : "s"}
          </Button>
        </div>
        <ErrorText message={error} />
      </CardContent>
    </Card>
  );
}
