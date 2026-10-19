"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { Clapperboard, Film, Loader2, Plus, RefreshCw } from "lucide-react";

import { ApiError } from "@/src/shared/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  createProject,
  listProjects,
  newIdempotencyKey,
  type FilmProjectSummary,
} from "./api";
import { characterId, parseBeats, parseDescriptors } from "./beats";
import { FilmProjectView } from "./FilmProjectView";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

const PROJECT_PARAM = "project";

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return friendlyErrorMessage(err);
  return "Something went wrong.";
}

function readSelectedFromUrl(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get(PROJECT_PARAM);
}

/** Mirror the open project in `?project=` so a reload or shared link reopens it. */
function writeSelectedToUrl(projectId: string | null): void {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (projectId) url.searchParams.set(PROJECT_PARAM, projectId);
  else url.searchParams.delete(PROJECT_PARAM);
  window.history.replaceState(window.history.state, "", url.toString());
}

/**
 * Film/Series Studio — the caller's film projects (GET /film/projects), a
 * form to plan + persist a new character-consistent shot list (POST
 * /film/projects with an idempotency key), and the open project's shots with
 * render, playback and final-export controls.
 */
export function FilmStudio() {
  const { getToken, isLoaded } = useAuth();

  const [title, setTitle] = React.useState("");
  const [name, setName] = React.useState("");
  const [style, setStyle] = React.useState("");
  const [descriptors, setDescriptors] = React.useState("");
  const [beatsText, setBeatsText] = React.useState("");
  const [totalShots, setTotalShots] = React.useState("");

  const [creating, setCreating] = React.useState(false);
  const [createError, setCreateError] = React.useState("");
  const [showCreate, setShowCreate] = React.useState(false);

  const [projects, setProjects] = React.useState<FilmProjectSummary[]>([]);
  const [listStatus, setListStatus] = React.useState<"loading" | "ready" | "error">("loading");
  const [listError, setListError] = React.useState("");
  const [selectedId, setSelectedId] = React.useState<string | null>(null);

  // A stable idempotency key per unsent draft; rotated after a successful create
  // so the *next* project isn't collapsed into the previous one.
  const idempotencyKeyRef = React.useRef<string>(newIdempotencyKey());

  const selectProject = React.useCallback((projectId: string | null) => {
    setSelectedId(projectId);
    writeSelectedToUrl(projectId);
  }, []);

  const loadProjects = React.useCallback(async () => {
    setListStatus((prev) => (prev === "ready" ? prev : "loading"));
    setListError("");
    try {
      const token = (await getToken()) ?? undefined;
      const rows = await listProjects({ limit: 100 }, { token });
      setProjects(rows);
      setListStatus("ready");
      const fromUrl = readSelectedFromUrl();
      setSelectedId((current) => current ?? fromUrl ?? rows[0]?.id ?? null);
      if (rows.length === 0 && !fromUrl) setShowCreate(true);
    } catch (err) {
      setListError(errorMessage(err));
      setListStatus("error");
    }
  }, [getToken]);

  React.useEffect(() => {
    if (isLoaded) void loadProjects();
  }, [isLoaded, loadProjects]);

  const onCreate = React.useCallback(async () => {
    setCreating(true);
    setCreateError("");
    try {
      const beats = parseBeats(beatsText);
      if (beats.length === 0) throw new Error("Add at least one beat.");
      const descriptorList = parseDescriptors(descriptors);
      const shots = parseInt(totalShots, 10);
      const token = (await getToken()) ?? undefined;

      const created = await createProject(
        {
          title: title.trim() || undefined,
          beats,
          character: {
            character_id: characterId(name),
            name: name.trim() || "Lead",
            descriptors: descriptorList.length > 0 ? descriptorList : undefined,
            style: style.trim() || undefined,
          },
          total_shots: Number.isFinite(shots) && shots > 0 ? shots : undefined,
        },
        { token, idempotencyKey: idempotencyKeyRef.current },
      );

      // Fresh key for the next distinct project submission.
      idempotencyKeyRef.current = newIdempotencyKey();
      setProjects((prev) => [created, ...prev.filter((p) => p.id !== created.id)]);
      setTitle("");
      setBeatsText("");
      setTotalShots("");
      setShowCreate(false);
      selectProject(created.id);
    } catch (err) {
      setCreateError(errorMessage(err));
    } finally {
      setCreating(false);
    }
  }, [beatsText, descriptors, totalShots, title, name, style, getToken, selectProject]);

  const handleRenamed = React.useCallback((id: string, newTitle: string) => {
    setProjects((prev) => prev.map((p) => (p.id === id ? { ...p, title: newTitle } : p)));
  }, []);

  const handleDeleted = React.useCallback(
    (id: string) => {
      const next = projects.filter((p) => p.id !== id);
      setProjects(next);
      selectProject(next[0]?.id ?? null);
      if (next.length === 0) setShowCreate(true);
    },
    [projects, selectProject],
  );

  return (
    <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
      <aside className="space-y-3" aria-label="Your films">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">Your films</h2>
          <div className="flex items-center gap-1">
            <Button
              size="icon"
              variant="ghost"
              className="h-8 w-8"
              onClick={() => void loadProjects()}
              aria-label="Refresh films"
              disabled={listStatus === "loading"}
            >
              <RefreshCw
                className={listStatus === "loading" ? "h-4 w-4 animate-spin" : "h-4 w-4"}
                aria-hidden
              />
            </Button>
            <Button size="sm" variant="outline" onClick={() => setShowCreate(true)}>
              <Plus className="mr-1 h-4 w-4" aria-hidden /> New
            </Button>
          </div>
        </div>
        {listStatus === "loading" && projects.length === 0 && (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading films
          </p>
        )}
        {listStatus === "error" && (
          <p className="text-sm text-destructive" role="alert">
            {listError}
          </p>
        )}
        {listStatus === "ready" && projects.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No films yet. Plan your first one with the form.
          </p>
        )}
        <ul className="space-y-1.5">
          {projects.map((p) => (
            <li key={p.id}>
              <button
                type="button"
                onClick={() => {
                  setShowCreate(false);
                  selectProject(p.id);
                }}
                aria-current={p.id === selectedId ? "true" : undefined}
                className={`w-full rounded-md border px-3 py-2 text-left transition-colors ${
                  p.id === selectedId
                    ? "border-primary/50 bg-primary/5"
                    : "border-border hover:bg-secondary/50"
                }`}
              >
                <span className="flex items-center gap-2 text-sm font-medium">
                  <Film className="h-4 w-4 shrink-0 text-primary" aria-hidden />
                  <span className="truncate">{p.title || "Untitled film"}</span>
                </span>
                <span className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                  <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
                    {p.has_final ? "Exported" : p.status.replace(/_/g, " ")}
                  </Badge>
                  {typeof p.shot_count === "number" && <span>{p.shot_count} shots</span>}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <div className="min-w-0 space-y-6">
        {showCreate && (
      <Card>
        <CardContent className="space-y-3 py-5">
          <div className="flex items-center gap-2">
            <Clapperboard className="h-4 w-4 text-primary" aria-hidden />
            <h2 className="font-semibold">New film project</h2>
            {projects.length > 0 && (
              <Button
                variant="ghost"
                size="sm"
                className="ml-auto"
                onClick={() => setShowCreate(false)}
              >
                Close
              </Button>
            )}
          </div>
          <label className="block text-xs text-muted-foreground">
            Project title
            <Input
              placeholder="e.g. Midnight Courier — Ep. 1"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
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
          <Button onClick={() => void onCreate()} disabled={creating}>
            {creating ? <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden /> : null}
            Create project
          </Button>
          {createError && <p className="text-sm text-destructive">{createError}</p>}
        </CardContent>
      </Card>

        )}

        {!showCreate && selectedId && (
          <FilmProjectView
            key={selectedId}
            projectId={selectedId}
            onRenamed={handleRenamed}
            onDeleted={handleDeleted}
          />
        )}

        {!showCreate && !selectedId && listStatus === "ready" && (
          <Card className="border-dashed">
            <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
              <Clapperboard className="h-6 w-6 text-primary" aria-hidden />
              <p className="text-sm text-muted-foreground">Pick a film or start a new one.</p>
              <Button onClick={() => setShowCreate(true)}>
                <Plus className="mr-1 h-4 w-4" aria-hidden /> New film project
              </Button>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
