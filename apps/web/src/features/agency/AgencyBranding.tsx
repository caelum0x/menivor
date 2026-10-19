"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { Image as ImageIcon } from "lucide-react";

import { ApiError } from "@/src/shared/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { getBrand, updateBrand, type Brand, type WatermarkPosition } from "./branding";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

const POSITIONS: WatermarkPosition[] = ["top_left", "top_right", "bottom_left", "bottom_right", "center"];

/** White-label watermark applied to every client's rendered output. */
export function AgencyBranding() {
  const { getToken } = useAuth();
  const [brand, setBrand] = React.useState<Brand | null>(null);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState("");
  const [saved, setSaved] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      const token = (await getToken()) ?? undefined;
      setBrand(await getBrand({ token }));
    } catch (err) {
      setError(friendlyErrorMessage(err, "Failed to load branding."));
    }
  }, [getToken]);

  React.useEffect(() => { void load(); }, [load]);

  const save = React.useCallback(async (patch: Partial<Brand>) => {
    if (!brand) return;
    setSaving(true);
    setSaved(false);
    setError("");
    try {
      const token = (await getToken()) ?? undefined;
      const next = await updateBrand({ ...brand, ...patch }, { token });
      setBrand(next);
      setSaved(true);
    } catch (err) {
      setError(friendlyErrorMessage(err, "Save failed."));
    } finally {
      setSaving(false);
    }
  }, [brand, getToken]);

  if (!brand) {
    return <Card><CardContent className="py-6 text-sm text-muted-foreground">{error || "Loading…"}</CardContent></Card>;
  }

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">White-label watermark</h2>

      <Card>
        <CardContent className="space-y-4 py-4">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">Enabled</span>
            <Button size="sm" variant={brand.enabled ? "default" : "outline"} onClick={() => void save({ enabled: !brand.enabled })}>
              {brand.enabled ? "On" : "Off"}
            </Button>
          </div>

          <div>
            <div className="mb-1 text-sm font-medium">Logo</div>
            {brand.logo_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={brand.logo_url} alt="Brand logo" className="h-16 w-auto rounded bg-muted p-1" />
            ) : (
              <div className="flex items-center gap-2 text-sm text-muted-foreground"><ImageIcon className="h-4 w-4" /> No logo — upload one on the Brand page.</div>
            )}
          </div>

          <div>
            <div className="mb-1 text-sm font-medium">Position</div>
            <div className="flex flex-wrap gap-2">
              {POSITIONS.map((p) => (
                <Button key={p} size="sm" variant={brand.position === p ? "default" : "outline"} onClick={() => void save({ position: p })}>
                  {p.replace("_", " ")}
                </Button>
              ))}
            </div>
          </div>

          <div>
            <div className="mb-1 text-sm font-medium">Opacity: {Math.round(brand.opacity * 100)}%</div>
            <div className="flex gap-2">
              {[0.25, 0.5, 0.75, 1].map((o) => (
                <Button key={o} size="sm" variant={Math.abs(brand.opacity - o) < 0.01 ? "default" : "outline"} onClick={() => void save({ opacity: o })}>
                  {Math.round(o * 100)}%
                </Button>
              ))}
            </div>
          </div>

          {saving ? <Badge variant="outline">Saving…</Badge> : saved ? <Badge variant="secondary">Saved</Badge> : null}
          {error ? <div className="text-sm text-red-600">{error}</div> : null}
        </CardContent>
      </Card>
    </div>
  );
}
