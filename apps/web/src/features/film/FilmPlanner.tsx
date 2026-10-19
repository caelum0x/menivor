"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { Clapperboard, Clock, Loader2 } from "lucide-react";

import { ApiError } from "@/src/shared/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { planFilm, type FilmPlan } from "./api";
import { characterId, parseBeats, parseDescriptors } from "./beats";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

/** Film planner: character + beats -> ordered shot list with runtime. */
export function FilmPlanner() {
  const { getToken } = useAuth();
  const [name, setName] = React.useState("");
  const [style, setStyle] = React.useState("");
  const [descriptors, setDescriptors] = React.useState("");
  const [beatsText, setBeatsText] = React.useState("");
  const [totalShots, setTotalShots] = React.useState("");
  const [plan, setPlan] = React.useState<FilmPlan | null>(null);
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  const onPlan = React.useCallback(async () => {
    setBusy(true);
    setError("");
    setPlan(null);
    try {
      const beats = parseBeats(beatsText);
      if (beats.length === 0) throw new Error("Add at least one beat.");
      const descriptorList = parseDescriptors(descriptors);
      const shots = parseInt(totalShots, 10);
      const token = (await getToken()) ?? undefined;
      const result = await planFilm(
        {
          beats,
          character: {
            character_id: characterId(name),
            name: name.trim() || "Lead",
            descriptors: descriptorList.length > 0 ? descriptorList : undefined,
            style: style.trim() || undefined,
          },
          total_shots: Number.isFinite(shots) && shots > 0 ? shots : undefined,
        },
        { token },
      );
      setPlan(result);
    } catch (err) {
      setError(friendlyErrorMessage(err, "Failed to plan."));
    } finally {
      setBusy(false);
    }
  }, [beatsText, descriptors, totalShots, name, style, getToken]);

  return (
    <div className="space-y-6">
      <Card>
        <CardContent className="space-y-3 py-5">
          <div className="flex items-center gap-2">
            <Clapperboard className="h-4 w-4 text-primary" aria-hidden />
            <h2 className="font-semibold">Plan a film</h2>
          </div>
          <div className="flex gap-2">
            <label className="flex-1 text-xs text-muted-foreground">
              Character name
              <Input placeholder="e.g. Mara" value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label className="flex-1 text-xs text-muted-foreground">
              Style
              <Input placeholder="e.g. noir, 35mm" value={style} onChange={(e) => setStyle(e.target.value)} />
            </label>
          </div>
          <label className="block text-xs text-muted-foreground">
            Descriptors (comma-separated)
            <Input
              placeholder="e.g. red coat, short hair, determined"
              value={descriptors}
              onChange={(e) => setDescriptors(e.target.value)}
            />
          </label>
          <label className="block text-xs text-muted-foreground">
            Beats — one per line, &quot;scene_id | summary&quot;
            <Textarea
              rows={6}
              placeholder={"s1 | Mara wakes to a ringing phone\ns2 | She races through empty streets"}
              value={beatsText}
              onChange={(e) => setBeatsText(e.target.value)}
            />
          </label>
          <label className="block text-xs text-muted-foreground">
            Total shots (optional)
            <Input
              inputMode="numeric"
              placeholder="auto"
              value={totalShots}
              onChange={(e) => setTotalShots(e.target.value)}
            />
          </label>
          <Button onClick={() => void onPlan()} disabled={busy}>
            {busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden /> : null}
            Plan shots
          </Button>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </CardContent>
      </Card>

      {plan && (
        <div className="space-y-3">
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Clock className="h-4 w-4" aria-hidden />
            {plan.shots.length} shots · {plan.total_runtime_s.toFixed(1)}s total runtime
          </p>
          <div className="space-y-3">
            {plan.shots.map((shot) => (
              <Card key={shot.shot_id}>
                <CardContent className="space-y-2 py-4">
                  <div className="flex items-center gap-2">
                    <Badge variant="secondary">#{shot.order}</Badge>
                    <Badge variant="outline">{shot.role}</Badge>
                    <Badge variant="outline">{shot.camera_motion}</Badge>
                    <span className="text-xs text-muted-foreground">
                      {shot.scene_id} · {shot.duration_s.toFixed(1)}s
                    </span>
                  </div>
                  <p className="text-sm">{shot.prompt}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
