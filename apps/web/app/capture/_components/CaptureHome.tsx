"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Loader2, ScanLine } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { ChipToggle, ErrorText, errorMessage, toggleIn, useRequestOptions } from "@/src/features/ad-studio/shared";
import {
  FORMAT_OPTIONS,
  KIND_HELP,
  KIND_LABELS,
  createCapture,
  detectCapture,
  getNativeStatus,
  type CaptureFormat,
  type DetectResult,
  type NativeStatus,
  type NewCaptureKind,
} from "./api";
import { CaptureList } from "./CaptureList";
import { EMPTY_NATIVE, NativeGameFields, nativeTarget, type NativeDraft } from "./NativeGameFields";

const KINDS: NewCaptureKind[] = ["website", "native_game", "app_store", "play_store"];
const DURATION_LIMITS: Record<string, { min: number; default: number; max: number }> = {
  website: { min: 10, default: 20, max: 45 },
  native_game: { min: 10, default: 30, max: 60 },
};

/** Paste a URL, pick formats and start a capture. */
export function CaptureHome({ initialUrl = "" }: { initialUrl?: string }) {
  const router = useRouter();
  const requestOptions = useRequestOptions();
  const [url, setUrl] = React.useState(initialUrl);
  const [detected, setDetected] = React.useState<DetectResult | null>(null);
  const [kind, setKind] = React.useState<NewCaptureKind | "auto">("auto");
  const [native, setNative] = React.useState<NativeDraft>(EMPTY_NATIVE);
  const [nativeStatus, setNativeStatus] = React.useState<NativeStatus | null>(null);
  const [formats, setFormats] = React.useState<CaptureFormat[]>(["9:16", "16:9"]);
  const [duration, setDuration] = React.useState<number | null>(null);
  const [cursor, setCursor] = React.useState(true);
  const [busy, setBusy] = React.useState<"" | "detect" | "create">("");
  const [error, setError] = React.useState("");

  const effectiveKind = kind === "auto" ? (detected?.kind ?? null) : kind;
  const limits = effectiveKind ? DURATION_LIMITS[effectiveKind] : undefined;
  const isStore = effectiveKind === "app_store" || effectiveKind === "play_store";
  const isNative = kind === "native_game";

  React.useEffect(() => {
    if (!isNative || nativeStatus) return;
    let cancelled = false;
    (async () => {
      try {
        const status = await getNativeStatus(await requestOptions());
        if (!cancelled) setNativeStatus(status);
      } catch (err) {
        if (!cancelled) setError(errorMessage(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isNative, nativeStatus, requestOptions]);

  const detect = async () => {
    const value = url.trim();
    if (!/^https?:\/\//i.test(value)) return;
    setBusy("detect");
    setError("");
    try {
      setDetected(await detectCapture(value, await requestOptions()));
    } catch (err) {
      setDetected(null);
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    const target = isNative ? nativeTarget(native, nativeStatus) : null;
    if (typeof target === "string") {
      setError(target);
      return;
    }
    if (!isNative && !/^https?:\/\//i.test(url.trim())) {
      setError("Paste a full link starting with https://");
      return;
    }
    if (formats.length === 0) {
      setError("Pick at least one format.");
      return;
    }
    setBusy("create");
    try {
      const capture = await createCapture(
        {
          ...(target ? { native: target } : { url: url.trim() }),
          kind,
          formats,
          cursor: isNative ? false : cursor,
          ...(limits && duration !== null ? { duration_s: duration } : {}),
        },
        await requestOptions(),
      );
      router.push(`/capture/${encodeURIComponent(capture.id)}`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy("");
    }
  };

  return (
    <div className="space-y-8">
      <Card>
        <CardContent className="space-y-5 p-5">
          <form onSubmit={submit} className="space-y-5" noValidate>
            {!isNative ? (
            <div className="space-y-2">
              <Label htmlFor="capture-url">Link</Label>
              <Input
                id="capture-url"
                type="url"
                inputMode="url"
                placeholder="https://yoursite.com, an App Store link or a Google Play link"
                value={url}
                onChange={(e) => {
                  setUrl(e.target.value);
                  setDetected(null);
                }}
                onBlur={detect}
                disabled={busy === "create"}
                autoComplete="off"
              />
              {busy === "detect" ? (
                <p className="text-xs text-muted-foreground">Checking the link...</p>
              ) : detected && kind === "auto" ? (
                <p className="text-xs text-muted-foreground">
                  Detected: <span className="font-medium text-foreground">{KIND_LABELS[detected.kind]}</span>
                </p>
              ) : null}
            </div>
            ) : null}

            <div className="grid gap-5 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="capture-kind">What is it?</Label>
                <Select
                  id="capture-kind"
                  value={kind}
                  onChange={(e) => {
                    setKind(e.target.value as NewCaptureKind | "auto");
                    setDuration(null);
                  }}
                >
                  <option value="auto">Detect from the link</option>
                  {KINDS.map((k) => (
                    <option key={k} value={k}>
                      {KIND_LABELS[k]}
                    </option>
                  ))}
                </Select>
                {effectiveKind ? <p className="text-xs text-muted-foreground">{KIND_HELP[effectiveKind]}</p> : null}
              </div>
              <div className="space-y-2">
                <span className="text-sm font-medium">Formats</span>
                <div className="flex flex-wrap gap-2" role="group" aria-label="Formats">
                  {FORMAT_OPTIONS.map((f) => (
                    <ChipToggle
                      key={f.id}
                      selected={formats.includes(f.id)}
                      onToggle={() => setFormats((cur) => toggleIn(cur, f.id))}
                    >
                      {f.label}
                    </ChipToggle>
                  ))}
                </div>
                <p className="text-xs text-muted-foreground">
                  {isNative
                    ? "The game is recorded once and fitted to each format."
                    : "Each format is recorded separately. 9:16 uses the mobile layout."}
                </p>
              </div>
            </div>

            {isNative ? (
              <NativeGameFields draft={native} onChange={setNative} status={nativeStatus} disabled={busy === "create"} />
            ) : null}

            {limits ? (
              <div className="space-y-2">
                <Label htmlFor="capture-duration">
                  Recording length: {duration ?? limits.default}s
                </Label>
                <input
                  id="capture-duration"
                  type="range"
                  min={limits.min}
                  max={limits.max}
                  step={1}
                  value={duration ?? limits.default}
                  onChange={(e) => setDuration(Number(e.target.value))}
                  className="w-full max-w-md accent-primary"
                />
              </div>
            ) : null}

            {!isStore && !isNative ? (
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={cursor} onChange={(e) => setCursor(e.target.checked)} />
                Show a highlighted cursor and click ripples
              </label>
            ) : null}

            <ErrorText message={error} />
            <Button type="submit" disabled={busy === "create"}>
              {busy === "create" ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <ScanLine className="mr-2 h-4 w-4" aria-hidden />
              )}
              Start capture
            </Button>
          </form>
        </CardContent>
      </Card>

      <CaptureList />
    </div>
  );
}
