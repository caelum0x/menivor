"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { Clapperboard, History, Loader2, Wand2 } from "lucide-react";

import { ApiError } from "@/src/shared/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  compileMotion,
  getMotion,
  getMotionHistory,
  listMotions,
  type MotionDetail,
  type MotionHistoryEntry,
  type MotionPlan,
  type MotionSummary,
} from "./api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

function errText(err: unknown, fallback: string): string {
  return friendlyErrorMessage(err, fallback);
}

/**
 * Motion / effects studio: browse the real camera-move catalog, inspect a
 * preset's detail, compile it at a chosen intensity into a deterministic plan,
 * and review your recent compiled moves — all wired to the /motion domain.
 */
export function MotionStudio() {
  const { getToken } = useAuth();
  const [motions, setMotions] = React.useState<MotionSummary[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");

  const [detail, setDetail] = React.useState<MotionDetail | null>(null);
  const [detailBusy, setDetailBusy] = React.useState(false);
  const [intensity, setIntensity] = React.useState(50);
  const [plan, setPlan] = React.useState<MotionPlan | null>(null);
  const [compiling, setCompiling] = React.useState(false);

  const [history, setHistory] = React.useState<MotionHistoryEntry[]>([]);
  const [historyError, setHistoryError] = React.useState("");

  const loadCatalog = React.useCallback(async () => {
    try {
      const token = (await getToken()) ?? undefined;
      const res = await listMotions({ token });
      setMotions(res.motions);
    } catch (err) {
      setError(errText(err, "Failed to load motions."));
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  const loadHistory = React.useCallback(async () => {
    try {
      const token = (await getToken()) ?? undefined;
      const res = await getMotionHistory({ limit: 25 }, { token });
      setHistory(res.history);
    } catch (err) {
      // History needs the DB; degrade gracefully without breaking the studio.
      setHistoryError(errText(err, "History unavailable."));
    }
  }, [getToken]);

  React.useEffect(() => {
    void loadCatalog();
    void loadHistory();
  }, [loadCatalog, loadHistory]);

  const onSelect = React.useCallback(
    async (preset: MotionSummary) => {
      setPlan(null);
      setDetailBusy(true);
      setError("");
      setIntensity(preset.intensity);
      try {
        const token = (await getToken()) ?? undefined;
        const full = await getMotion(preset.id, { token });
        setDetail(full);
      } catch (err) {
        setError(errText(err, "Failed to open preset."));
      } finally {
        setDetailBusy(false);
      }
    },
    [getToken],
  );

  const onCompile = React.useCallback(async () => {
    if (!detail) return;
    setCompiling(true);
    setError("");
    try {
      const token = (await getToken()) ?? undefined;
      const res = await compileMotion(detail.id, { intensity }, { token });
      setPlan(res);
      await loadHistory();
    } catch (err) {
      setError(errText(err, "Failed to compile motion."));
    } finally {
      setCompiling(false);
    }
  }, [detail, intensity, getToken, loadHistory]);

  return (
    <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
      <div className="space-y-4">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Clapperboard className="h-4 w-4" aria-hidden /> Camera-move catalog
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
        {loading ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading motions…
          </p>
        ) : motions.length === 0 ? (
          <p className="text-sm text-muted-foreground">No motions available.</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {motions.map((m) => (
              <Card key={m.id}>
                <CardContent className="space-y-2 py-4">
                  <div className="flex items-start justify-between gap-2">
                    <button
                      type="button"
                      className="text-left font-medium hover:underline"
                      onClick={() => void onSelect(m)}
                    >
                      {m.name}
                    </button>
                    <Badge variant={m.requires_provider ? "secondary" : "outline"}>
                      {m.render_class}
                    </Badge>
                  </div>
                  <p className="text-sm text-muted-foreground">{m.description}</p>
                  <div className="flex flex-wrap gap-1">
                    {m.tags.map((t) => (
                      <Badge key={t} variant="outline">
                        {t}
                      </Badge>
                    ))}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        {detail && (
          <Card>
            <CardContent className="space-y-3 py-5">
              <div className="flex items-center gap-2">
                <Wand2 className="h-4 w-4 text-primary" aria-hidden />
                <h2 className="font-semibold">{detail.name}</h2>
                <Badge variant="outline">{detail.category}</Badge>
              </div>
              {detailBusy ? (
                <p className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading detail…
                </p>
              ) : (
                <>
                  <p className="text-sm text-muted-foreground">{detail.description}</p>
                  {detail.model && (
                    <p className="text-sm">
                      <span className="font-medium">Camera:</span> {detail.model.camera_pose} ·{" "}
                      {detail.model.prompt_fragment}
                    </p>
                  )}
                  {detail.filter && (
                    <p className="text-sm">
                      <span className="font-medium">FFmpeg:</span> {detail.filter.camera_motion}
                    </p>
                  )}
                  <label className="block text-sm" htmlFor="motion-intensity">
                    Intensity: <span className="font-medium">{intensity}</span>
                  </label>
                  <input
                    id="motion-intensity"
                    type="range"
                    min={0}
                    max={100}
                    value={intensity}
                    onChange={(e) => setIntensity(Number(e.target.value))}
                    className="w-full"
                  />
                  <Button onClick={() => void onCompile()} disabled={compiling}>
                    {compiling ? (
                      <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden />
                    ) : null}
                    Compile motion plan
                  </Button>
                </>
              )}
              {plan && (
                <div className="space-y-1 rounded-md border bg-muted/40 p-3 text-sm">
                  <p>
                    <span className="font-medium">Class:</span> {plan.motion_class}
                  </p>
                  {plan.model && (
                    <p className="text-muted-foreground">
                      <span className="font-medium">Pose:</span> {plan.model.camera_pose} ·{" "}
                      {plan.model.length} frames · {plan.model.width}×{plan.model.height}
                    </p>
                  )}
                  {plan.filter && (
                    <p className="text-muted-foreground">
                      <span className="font-medium">Filter:</span> {plan.filter.camera_motion} @{" "}
                      {plan.filter.intensity}
                    </p>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        )}
      </div>

      <div className="space-y-3">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <History className="h-4 w-4" aria-hidden /> Recent moves
        </div>
        {historyError ? (
          <p className="text-sm text-muted-foreground">{historyError}</p>
        ) : history.length === 0 ? (
          <p className="text-sm text-muted-foreground">No compiled moves yet.</p>
        ) : (
          <div className="space-y-2">
            {history.map((h) => (
              <Card key={h.id}>
                <CardContent className="flex items-center justify-between gap-2 py-3 text-sm">
                  <span className="font-medium">{h.preset_id}</span>
                  <span className="text-muted-foreground">
                    {h.motion_class} · {h.intensity}
                  </span>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
