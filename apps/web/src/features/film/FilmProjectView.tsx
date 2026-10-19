"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import {
  Check,
  Clock,
  Download,
  Film,
  Loader2,
  Pencil,
  Play,
  RefreshCw,
  RotateCcw,
  Scissors,
  Trash2,
  X,
} from "lucide-react";

import { ApiError } from "@/src/shared/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Select } from "@/components/ui/select";
import {
  deleteProject,
  exportFilm,
  getProject,
  renameProject,
  renderAllShots,
  renderShot,
  shotOutputUrls,
  type FilmProject,
  type ProjectShot,
} from "./api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { safeServerText } from "@/src/shared/errors/friendly";

const POLL_MS = 5_000;
const TITLE_MAX = 200;

/** Per-shot wallet hold options (micro-USD). Only the actual cost is charged. */
const SHOT_BUDGETS = [
  { micros: 50_000, label: "$0.05" },
  { micros: 100_000, label: "$0.10" },
  { micros: 250_000, label: "$0.25" },
] as const;

const SHOT_STATUS_LABEL: Record<string, string> = {
  pending: "Not rendered",
  rendering: "Rendering",
  done: "Rendered",
  failed: "Failed",
};

const PROJECT_STATUS_LABEL: Record<string, string> = {
  planned: "Planned",
  rendering: "Rendering shots",
  shots_ready: "Ready to export",
  exporting: "Exporting",
  exported: "Exported",
  failed: "Needs attention",
};

function messageOf(err: unknown, fallback: string): string {
  return friendlyErrorMessage(err, fallback);
}

function needsPolling(project: FilmProject): boolean {
  return (
    project.shots.some((s) => s.status === "rendering") ||
    project.export_state === "queued" ||
    project.export_state === "running"
  );
}

export interface FilmProjectViewProps {
  projectId: string;
  /** Called after a rename so the project list can update its row. */
  onRenamed?: (id: string, title: string) => void;
  /** Called after the project was deleted. */
  onDeleted?: (id: string) => void;
}

/**
 * One persisted film: its locked shots with per-shot render / new-take
 * controls and playback, a "render all" action (one wallet hold per shot),
 * and the final export that stitches every rendered shot into one MP4.
 * Polls while shots are rendering or the export is running.
 */
export function FilmProjectView({ projectId, onRenamed, onDeleted }: Readonly<FilmProjectViewProps>) {
  const { getToken } = useAuth();
  const [project, setProject] = React.useState<FilmProject | null>(null);
  const [loadError, setLoadError] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const [actionError, setActionError] = React.useState("");
  const [notice, setNotice] = React.useState("");
  const [busy, setBusy] = React.useState<string>("");
  const [budget, setBudget] = React.useState<number>(SHOT_BUDGETS[0].micros);
  const [renaming, setRenaming] = React.useState(false);
  const [titleDraft, setTitleDraft] = React.useState("");

  const load = React.useCallback(
    async (signal?: AbortSignal) => {
      try {
        const token = (await getToken()) ?? undefined;
        const detail = await getProject(projectId, { token, signal });
        setProject(detail);
        setLoadError("");
      } catch (err) {
        if (signal?.aborted) return;
        setLoadError(messageOf(err, "Couldn't load this film."));
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [getToken, projectId],
  );

  React.useEffect(() => {
    setLoading(true);
    setProject(null);
    setActionError("");
    setNotice("");
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const polling = project ? needsPolling(project) : false;
  React.useEffect(() => {
    if (!polling) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => void load(controller.signal), POLL_MS);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [polling, project, load]);

  const run = React.useCallback(
    async (key: string, fallback: string, action: (token?: string) => Promise<void>) => {
      if (busy) return;
      setBusy(key);
      setActionError("");
      setNotice("");
      try {
        const token = (await getToken()) ?? undefined;
        await action(token);
        await load();
      } catch (err) {
        setActionError(messageOf(err, fallback));
      } finally {
        setBusy("");
      }
    },
    [busy, getToken, load],
  );

  const onRenderAll = () =>
    run("all", "Couldn't start rendering.", async (token) => {
      const result = await renderAllShots(projectId, { max_cost_micros: budget }, { token });
      const started = result.started.length;
      const remaining = result.remaining ?? 0;
      if (result.error) {
        setActionError(
          `${started} shot${started === 1 ? "" : "s"} started, ${remaining} waiting: ${safeServerText(result.error, "some shots could not start yet.")}`,
        );
      } else {
        setNotice(
          started === 0
            ? "Every shot is already rendering or rendered."
            : `Rendering ${started} shot${started === 1 ? "" : "s"}.`,
        );
      }
    });

  const onRenderShot = (shot: ProjectShot) =>
    run(`shot:${shot.shot_id}`, "Couldn't start this shot.", async (token) => {
      await renderShot(
        projectId,
        shot.shot_id,
        { max_cost_micros: budget, rerender: shot.status === "done" },
        { token },
      );
      setNotice(`Shot ${shot.order + 1} is rendering.`);
    });

  const onExport = () =>
    run("export", "Couldn't start the export.", async (token) => {
      await exportFilm(projectId, { token });
      setNotice("Stitching your shots into the final film.");
    });

  const onRename = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const title = titleDraft.trim();
    if (!title) return;
    await run("rename", "Couldn't rename this film.", async (token) => {
      const updated = await renameProject(projectId, title.slice(0, TITLE_MAX), { token });
      onRenamed?.(projectId, updated.title);
      setRenaming(false);
    });
  };

  const onDelete = async () => {
    const ok = window.confirm(
      "Delete this film? Shots still rendering are cancelled and refunded. Finished shot renders stay in your render history.",
    );
    if (!ok || busy) return;
    setBusy("delete");
    setActionError("");
    try {
      const token = (await getToken()) ?? undefined;
      await deleteProject(projectId, { token });
      onDeleted?.(projectId);
    } catch (err) {
      setActionError(messageOf(err, "Couldn't delete this film."));
    } finally {
      setBusy("");
    }
  };

  if (loading && !project) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading film
      </p>
    );
  }

  if (!project) {
    return (
      <Card className="border-destructive/40">
        <CardContent className="flex items-center justify-between gap-3 py-4">
          <p className="text-sm text-destructive">{loadError || "This film could not be found."}</p>
          <Button size="sm" variant="outline" onClick={() => void load()}>
            <RefreshCw className="mr-1 h-4 w-4" aria-hidden /> Try again
          </Button>
        </CardContent>
      </Card>
    );
  }

  const shots = project.shots;
  const doneCount = shots.filter((s) => s.status === "done").length;
  const renderingCount = shots.filter((s) => s.status === "rendering").length;
  const pendingCount = shots.length - doneCount - renderingCount;
  const exporting = project.export_state === "queued" || project.export_state === "running";
  const canExport =
    project.can_export ?? (shots.length > 0 && doneCount === shots.length && !exporting);
  const finalUrl = project.export_state === "done" ? project.final_url : null;

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="space-y-4 py-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            {renaming ? (
              <form onSubmit={(e) => void onRename(e)} className="flex items-center gap-1.5">
                <Label htmlFor="film-title" className="sr-only">
                  Film title
                </Label>
                <Input
                  id="film-title"
                  value={titleDraft}
                  maxLength={TITLE_MAX}
                  onChange={(e) => setTitleDraft(e.target.value)}
                  className="h-9 w-64"
                  autoFocus
                />
                <Button type="submit" size="icon" variant="ghost" className="h-9 w-9" disabled={busy !== "" || !titleDraft.trim()} aria-label="Save title">
                  <Check className="h-4 w-4" aria-hidden />
                </Button>
                <Button type="button" size="icon" variant="ghost" className="h-9 w-9" onClick={() => setRenaming(false)} aria-label="Cancel rename">
                  <X className="h-4 w-4" aria-hidden />
                </Button>
              </form>
            ) : (
              <div className="min-w-0">
                <h3 className="flex items-center gap-2 text-lg font-semibold">
                  <Film className="h-5 w-5 shrink-0 text-primary" aria-hidden />
                  <span className="truncate">{project.title || "Untitled film"}</span>
                </h3>
                <p className="mt-1 flex items-center gap-2 text-sm text-muted-foreground">
                  <Clock className="h-4 w-4" aria-hidden />
                  {shots.length} shots · {project.total_runtime_s.toFixed(1)}s runtime ·{" "}
                  {doneCount}/{shots.length} rendered
                </p>
              </div>
            )}
            <div className="flex items-center gap-1">
              <Badge variant="secondary">
                {PROJECT_STATUS_LABEL[project.status] ?? project.status}
              </Badge>
              {!renaming && (
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-9 w-9"
                  onClick={() => {
                    setTitleDraft(project.title || "");
                    setRenaming(true);
                  }}
                  aria-label="Rename film"
                  title="Rename"
                >
                  <Pencil className="h-4 w-4" aria-hidden />
                </Button>
              )}
              <Button
                size="icon"
                variant="ghost"
                className="h-9 w-9 text-muted-foreground hover:text-destructive"
                onClick={() => void onDelete()}
                disabled={busy !== "" || project.export_state === "running"}
                aria-label="Delete film"
                title="Delete"
              >
                <Trash2 className="h-4 w-4" aria-hidden />
              </Button>
            </div>
          </div>

          {shots.length > 0 && (
            <Progress
              value={Math.round((doneCount / shots.length) * 100)}
              aria-label="Shots rendered"
            />
          )}

          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="shot-budget">Spend cap per shot</Label>
              <Select
                id="shot-budget"
                value={String(budget)}
                onChange={(e) => setBudget(Number(e.target.value))}
                className="w-36"
              >
                {SHOT_BUDGETS.map((b) => (
                  <option key={b.micros} value={b.micros}>
                    Up to {b.label}
                  </option>
                ))}
              </Select>
            </div>
            <Button
              onClick={() => void onRenderAll()}
              disabled={busy !== "" || pendingCount === 0 || exporting}
            >
              {busy === "all" ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <Play className="mr-1 h-4 w-4" aria-hidden />
              )}
              Render {pendingCount > 0 ? `${pendingCount} remaining shot${pendingCount === 1 ? "" : "s"}` : "all shots"}
            </Button>
            <Button
              variant="secondary"
              onClick={() => void onExport()}
              disabled={busy !== "" || !canExport}
              title={canExport ? undefined : "Render every shot first"}
            >
              {busy === "export" || exporting ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <Scissors className="mr-1 h-4 w-4" aria-hidden />
              )}
              {exporting
                ? "Exporting final film"
                : project.export_state === "done"
                  ? "Export again"
                  : "Export final film"}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => void load()} disabled={busy !== ""}>
              <RefreshCw className="mr-1 h-4 w-4" aria-hidden /> Refresh
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Each shot holds its spend cap from your wallet and is charged only the actual cost;
            failed or cancelled shots are refunded. Exporting the final film is free.
          </p>
          {renderingCount > 0 && (
            <p className="text-sm text-muted-foreground">
              {renderingCount} shot{renderingCount === 1 ? " is" : "s are"} rendering. This page
              updates automatically.
            </p>
          )}
          {notice && <p className="text-sm text-muted-foreground">{notice}</p>}
          {actionError && (
            <p className="text-sm text-destructive" role="alert">
              {actionError}
            </p>
          )}
          {project.export_state === "failed" && project.export_error && (
            <p className="text-sm text-destructive">Export failed: {project.export_error}</p>
          )}
        </CardContent>
      </Card>

      {finalUrl && (
        <Card>
          <CardContent className="space-y-3 py-5">
            <h4 className="font-semibold">Final film</h4>
            <video
              src={finalUrl}
              controls
              playsInline
              preload="metadata"
              className="w-full max-w-xl rounded-md border border-border bg-black"
              aria-label="Final stitched film"
            />
            <Button asChild size="sm" variant="outline">
              <a
                href={project.final_download_url || finalUrl}
                download
                target="_blank"
                rel="noopener noreferrer"
              >
                <Download className="mr-1 h-4 w-4" aria-hidden /> Download MP4
              </a>
            </Button>
          </CardContent>
        </Card>
      )}

      <div className="space-y-3">
        {shots.map((shot) => (
          <ShotCard
            key={shot.shot_id}
            shot={shot}
            busy={busy !== ""}
            starting={busy === `shot:${shot.shot_id}`}
            locked={exporting}
            onRender={() => void onRenderShot(shot)}
          />
        ))}
      </div>
    </div>
  );
}

function ShotCard({
  shot,
  busy,
  starting,
  locked,
  onRender,
}: Readonly<{
  shot: ProjectShot;
  busy: boolean;
  starting: boolean;
  locked: boolean;
  onRender: () => void;
}>) {
  const urls = shotOutputUrls(shot);
  const rendering = shot.status === "rendering";
  const done = shot.status === "done";
  return (
    <Card>
      <CardContent className="space-y-2 py-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">#{shot.order + 1}</Badge>
            <Badge variant="outline">{shot.role}</Badge>
            <Badge variant="outline">{shot.camera_motion}</Badge>
            <Badge variant={done ? "secondary" : shot.status === "failed" ? "destructive" : "outline"}>
              {rendering && <Loader2 className="mr-1 h-3 w-3 animate-spin" aria-hidden />}
              {SHOT_STATUS_LABEL[shot.status] ?? shot.status}
            </Badge>
            <span className="text-xs text-muted-foreground">
              {(shot.duration_ms / 1000).toFixed(1)}s · seed {shot.seed}
            </span>
          </div>
          {!rendering && (
            <Button size="sm" variant="outline" onClick={onRender} disabled={busy || locked}>
              {starting ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden />
              ) : done ? (
                <RotateCcw className="mr-1 h-4 w-4" aria-hidden />
              ) : (
                <Play className="mr-1 h-4 w-4" aria-hidden />
              )}
              {done ? "New take" : shot.status === "failed" ? "Retry shot" : "Render shot"}
            </Button>
          )}
        </div>
        <p className="text-sm">{shot.prompt}</p>
        {shot.status === "failed" && shot.render_error && (
          <p className="text-xs text-destructive">{shot.render_error}</p>
        )}
        {urls.length > 0 && (
          <div className="flex flex-wrap items-end gap-3">
            <video
              src={urls[0]}
              controls
              playsInline
              preload="metadata"
              className="w-full max-w-xs rounded-md border border-border bg-black"
              aria-label={`Shot ${shot.order + 1} render`}
            />
            <Button asChild size="sm" variant="ghost">
              <a href={urls[0]} download target="_blank" rel="noopener noreferrer">
                <Download className="mr-1 h-4 w-4" aria-hidden /> Download shot
              </a>
            </Button>
          </div>
        )}
        {done && urls.length === 0 && (shot.unusable_output_refs ?? 0) > 0 && (
          <p className="text-xs text-muted-foreground">
            This shot rendered, but its video is not downloadable from here yet.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
