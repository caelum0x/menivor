"use client";

import * as React from "react";
import { AlertCircle, Check, Loader2, RotateCcw, Save } from "lucide-react";
import {
  isWatermarkPosition,
  WATERMARK_DEFAULT_POSITION,
  type BrandUpdateRequest,
  type WatermarkPosition,
} from "@/lib/types";
import { ApiError, presignAndUpload } from "@/lib/api";
import { useApiToken } from "@/lib/use-api-token";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { useBrand } from "@/components/brand/use-brand";
import { EnabledToggle } from "@/components/brand/EnabledToggle";
import {
  LogoUploader,
  type LogoSelection,
} from "@/components/brand/LogoUploader";
import { OpacitySlider } from "@/components/brand/OpacitySlider";
import { PositionPicker } from "@/components/brand/PositionPicker";
import { WatermarkPreview } from "@/components/brand/WatermarkPreview";
import { clampOpacity } from "@/components/brand/brand-utils";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

type SavePhase =
  | { status: "idle" }
  | { status: "uploading"; progress: number }
  | { status: "saving" }
  | { status: "error"; message: string }
  | { status: "saved" };

function toPosition(value: string): WatermarkPosition {
  return isWatermarkPosition(value) ? value : WATERMARK_DEFAULT_POSITION;
}

/**
 * The Brand Watermark editor. Loads the caller's settings, lets them upload a
 * logo, pick a corner, set opacity, and toggle it on/off, with a live preview of
 * the placement. On save it uploads any newly-picked logo (presign + PUT), then
 * PUTs the changed brand fields. Draft state is re-seeded from the server after
 * each successful save so the form always mirrors what is persisted.
 */
export function BrandEditor() {
  const getApiToken = useApiToken();
  const { status, brand, errorMessage, saving, reload, save } = useBrand();

  // Draft state (seeded from the server brand; edited locally until saved).
  const [position, setPosition] = React.useState<WatermarkPosition>(
    WATERMARK_DEFAULT_POSITION,
  );
  const [opacity, setOpacity] = React.useState(0.85);
  const [enabled, setEnabled] = React.useState(true);
  const [pendingLogo, setPendingLogo] = React.useState<LogoSelection | null>(
    null,
  );
  const [logoCleared, setLogoCleared] = React.useState(false);
  const [phase, setPhase] = React.useState<SavePhase>({ status: "idle" });

  // Revoke the previous object URL whenever the pending logo changes / unmounts.
  const prevUrlRef = React.useRef<string | null>(null);
  React.useEffect(() => {
    const url = pendingLogo?.url ?? null;
    if (prevUrlRef.current && prevUrlRef.current !== url) {
      URL.revokeObjectURL(prevUrlRef.current);
    }
    prevUrlRef.current = url;
  }, [pendingLogo]);
  React.useEffect(
    () => () => {
      if (prevUrlRef.current) URL.revokeObjectURL(prevUrlRef.current);
    },
    [],
  );

  // (Re)seed the draft from the server brand on load and after each save. Phase
  // is deliberately NOT reset here — the save/reset handlers own its lifecycle,
  // so the post-save "saved" note isn't clobbered by this effect.
  React.useEffect(() => {
    if (!brand) return;
    setPosition(toPosition(brand.position));
    setOpacity(clampOpacity(brand.opacity));
    setEnabled(brand.enabled);
    setPendingLogo(null);
    setLogoCleared(false);
  }, [brand]);

  const storedLogoUrl = brand?.logo_url ?? null;
  const hasStoredLogo = Boolean(brand?.logo_key);

  // The effective logo shown in the preview + uploader.
  const previewLogoUrl = pendingLogo
    ? pendingLogo.url
    : logoCleared
      ? null
      : storedLogoUrl;

  const handleSelectLogo = React.useCallback((selection: LogoSelection) => {
    setLogoCleared(false);
    setPendingLogo(selection);
  }, []);

  const handleClearLogo = React.useCallback(() => {
    setPendingLogo(null);
    if (hasStoredLogo) setLogoCleared(true);
  }, [hasStoredLogo]);

  const dirty =
    brand !== null &&
    (position !== toPosition(brand.position) ||
      clampOpacity(opacity) !== clampOpacity(brand.opacity) ||
      enabled !== brand.enabled ||
      pendingLogo !== null ||
      logoCleared);

  const busy =
    saving ||
    phase.status === "uploading" ||
    phase.status === "saving";

  const handleReset = React.useCallback(() => {
    if (!brand) return;
    setPosition(toPosition(brand.position));
    setOpacity(clampOpacity(brand.opacity));
    setEnabled(brand.enabled);
    setPendingLogo(null);
    setLogoCleared(false);
    setPhase({ status: "idle" });
  }, [brand]);

  const handleSave = React.useCallback(async () => {
    if (!brand || busy) return;
    setPhase({ status: "idle" });

    const patch: BrandUpdateRequest = {
      position,
      opacity: clampOpacity(opacity),
      enabled,
    };

    try {
      const token = await getApiToken();

      if (pendingLogo) {
        setPhase({ status: "uploading", progress: 0 });
        const { key } = await presignAndUpload(pendingLogo.file, {
          token,
          onProgress: (fraction) =>
            setPhase({
              status: "uploading",
              progress: Math.round(fraction * 100),
            }),
        });
        patch.logo_key = key;
      } else if (logoCleared) {
        patch.logo_key = "";
      }

      setPhase({ status: "saving" });
      const updated = await save(patch);
      // `save` re-seeds the draft via the brand effect; surface a success note.
      setPhase(updated ? { status: "saved" } : { status: "idle" });
    } catch (err) {
      const message =
        friendlyErrorMessage(err, "Could not save your brand settings. Please try again.");
      setPhase({ status: "error", message });
    }
  }, [
    brand,
    busy,
    enabled,
    getApiToken,
    logoCleared,
    opacity,
    pendingLogo,
    position,
    save,
  ]);

  if (status === "loading") {
    return (
      <div className="grid gap-8 lg:grid-cols-[1fr_20rem]">
        <div className="space-y-6">
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
        <Skeleton className="mx-auto aspect-[9/16] w-full max-w-[16rem]" />
      </div>
    );
  }

  if (status === "error" && !brand) {
    return (
      <Card className="border-destructive/40">
        <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
          <AlertCircle className="size-6 text-destructive" aria-hidden />
          <p className="text-sm text-muted-foreground">
            {errorMessage || "Could not load your brand settings."}
          </p>
          <Button variant="outline" size="sm" onClick={reload}>
            <RotateCcw /> Try again
          </Button>
        </CardContent>
      </Card>
    );
  }

  const saveError = phase.status === "error" ? phase.message : errorMessage;

  return (
    <div className="grid gap-8 lg:grid-cols-[1fr_20rem]">
      <div className="space-y-6">
        <Card>
          <CardContent className="space-y-6 p-6">
            <div className="space-y-2">
              <Label>Logo</Label>
              <LogoUploader
                pendingUrl={pendingLogo?.url ?? null}
                storedUrl={logoCleared ? null : storedLogoUrl}
                onSelect={handleSelectLogo}
                onClear={handleClearLogo}
                disabled={busy}
              />
            </div>

            <div className="space-y-2">
              <Label>Position</Label>
              <PositionPicker
                value={position}
                onChange={setPosition}
                disabled={busy}
              />
            </div>

            <OpacitySlider
              value={opacity}
              onChange={setOpacity}
              disabled={busy}
            />

            <EnabledToggle
              checked={enabled}
              onChange={setEnabled}
              disabled={busy}
            />
          </CardContent>
        </Card>

        {phase.status === "uploading" && (
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              Uploading logo… {phase.progress}%
            </p>
            <Progress value={phase.progress} />
          </div>
        )}

        {saveError && (
          <p
            role="alert"
            className="flex items-center gap-2 text-sm text-destructive"
          >
            <AlertCircle className="size-4 shrink-0" aria-hidden />
            {saveError}
          </p>
        )}

        {phase.status === "saved" && !dirty && (
          <p className="flex items-center gap-2 text-sm text-success">
            <Check className="size-4 shrink-0" aria-hidden />
            Brand settings saved.
          </p>
        )}

        <div className="flex items-center gap-3">
          <Button onClick={() => void handleSave()} disabled={!dirty || busy}>
            {busy ? (
              <>
                <Loader2 className="animate-spin" />
                {phase.status === "uploading" ? "Uploading…" : "Saving…"}
              </>
            ) : (
              <>
                <Save /> Save changes
              </>
            )}
          </Button>
          <Button
            variant="ghost"
            onClick={handleReset}
            disabled={!dirty || busy}
          >
            Reset
          </Button>
        </div>
      </div>

      <div className="lg:sticky lg:top-6 lg:self-start">
        <p className="mb-3 text-sm font-medium">Preview</p>
        <WatermarkPreview
          logoUrl={previewLogoUrl}
          position={position}
          opacity={opacity}
          enabled={enabled}
        />
      </div>
    </div>
  );
}
