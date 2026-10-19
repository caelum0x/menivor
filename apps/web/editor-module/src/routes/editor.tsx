import { createFileRoute } from "@tanstack/react-router";
import { type CSSProperties, useCallback, useEffect, useRef, useState } from "react";

import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import {
  NativeSelect,
  NativeSelectOption,
} from "../components/ui/native-select";
import {
  ApiError,
  POLL_INTERVAL_MS,
  createTimelineExport,
  errorMessage,
  getJob,
  listMusic,
  newIdempotencyKey,
} from "../lib/editor-api";
import {
  MAX_MUSIC_VOLUME,
  MAX_SPEED,
  MIN_MUSIC_VOLUME,
  MIN_SPEED,
  type EditorSource,
  type MusicSelection,
  type MusicTrack,
  type OverlayPosition,
  type TextOverlay,
  type TimelineSegment,
  formatTimecode,
  mapJobToEditorSource,
  mapMusicCatalog,
  moveSegment,
  moveSegmentToIndex,
  newMusicSelection,
  newOverlay,
  newSegment,
  timelineDuration,
  toTimelineExportBody,
  validateTimeline,
} from "../lib/editor-model";

/**
 * Standalone, functional reel editor wired to the real Menivor API.
 *
 * Load an owned reel (job) by id, then build a non-destructive EDL over its
 * rendered source: trim/reorder/speed clips, edit per-clip captions, add text
 * overlays, and submit a `timeline-exports` job. Everything runs against the
 * shared wire client in `../lib/editor-api` with the pure model in
 * `../lib/editor-model` — no placeholder, no mock data.
 */
export const Route = createFileRoute("/editor")({
  component: Editor,
  validateSearch: (search: Record<string, unknown>): { job?: string } => ({
    job: typeof search.job === "string" ? search.job : undefined,
  }),
});

type LoadState = "idle" | "loading" | "loaded" | "error";

function Editor() {
  const { job: jobParam } = Route.useSearch();

  const [jobId, setJobId] = useState<string>(jobParam ?? "");
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [source, setSource] = useState<EditorSource | null>(null);
  const [loadError, setLoadError] = useState<string>("");

  const [sourceDuration, setSourceDuration] = useState<number>(0);
  const [segments, setSegments] = useState<TimelineSegment[]>([]);
  const [overlays, setOverlays] = useState<TextOverlay[]>([]);
  const [music, setMusic] = useState<MusicSelection>(newMusicSelection());
  const [musicTracks, setMusicTracks] = useState<MusicTrack[]>([]);
  const [seededForJob, setSeededForJob] = useState<string>("");

  const [saving, setSaving] = useState<boolean>(false);
  const [saveMessage, setSaveMessage] = useState<string>("");
  const [saveError, setSaveError] = useState<string>("");

  const videoRef = useRef<HTMLVideoElement>(null);
  const dragId = useRef<string | null>(null);
  const [dragOverId, setDragOverId] = useState<string | null>(null);

  // --- Load the curated background-music catalog (real GET /catalog/music) -- //
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const entries = await listMusic({ signal: controller.signal });
        setMusicTracks(mapMusicCatalog(entries));
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        // A missing/empty catalog is non-fatal: music is simply unavailable.
        setMusicTracks([]);
      }
    })();
    return () => controller.abort();
  }, []);

  // --- Load + poll the source job ------------------------------------------ //
  const loadJob = useCallback(async (id: string, signal: AbortSignal) => {
    const trimmed = id.trim();
    if (!trimmed) {
      setLoadState("error");
      setLoadError("Enter a job id to load a reel.");
      return;
    }
    setLoadState("loading");
    setLoadError("");
    try {
      // Poll until the render reaches a terminal state (complete/failed).
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const job = await getJob(trimmed, { signal });
        const mapped = mapJobToEditorSource(job);
        setSource(mapped);
        if (mapped.terminal) {
          if (mapped.failed) {
            setLoadState("error");
            setLoadError(mapped.error || "This reel failed to render.");
          } else {
            setLoadState("loaded");
          }
          return;
        }
        await sleep(POLL_INTERVAL_MS, signal);
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setLoadState("error");
      setLoadError(
        errorMessage(error, "Could not load the reel. Check the job id and your session."),
      );
    }
  }, []);

  // Auto-load when a `?job=` param is present on mount.
  useEffect(() => {
    if (!jobParam) return;
    const controller = new AbortController();
    void loadJob(jobParam, controller.signal);
    return () => controller.abort();
  }, [jobParam, loadJob]);

  const onLoadClick = useCallback(() => {
    const controller = new AbortController();
    // Reset the derived EDL so a new source re-seeds cleanly.
    setSegments([]);
    setOverlays([]);
    setMusic(newMusicSelection());
    setSeededForJob("");
    setSourceDuration(0);
    setSaveMessage("");
    setSaveError("");
    void loadJob(jobId, controller.signal);
  }, [jobId, loadJob]);

  // Seed a single full-length segment once the source metadata is known.
  const onVideoMetadata = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    const duration = Number(video.duration);
    if (!Number.isFinite(duration) || duration <= 0) return;
    setSourceDuration(duration);
    if (source && seededForJob !== source.jobId) {
      setSegments([newSegment(0, Number(duration.toFixed(3)))]);
      setSeededForJob(source.jobId);
    }
  }, [source, seededForJob]);

  // --- Immutable timeline edits -------------------------------------------- //
  const updateSegment = useCallback(
    (id: string, patch: Partial<TimelineSegment>) => {
      setSegments((prev) => prev.map((s) => (s.id === id ? { ...s, ...patch } : s)));
    },
    [],
  );

  const removeSegment = useCallback((id: string) => {
    setSegments((prev) => prev.filter((s) => s.id !== id));
  }, []);

  const reorder = useCallback((id: string, direction: -1 | 1) => {
    setSegments((prev) => moveSegment(prev, id, direction));
  }, []);

  // Drag-and-drop reorder: dropping clip `sourceId` onto `targetId` moves it
  // to the target's current slot (immutably via the pure model helper).
  const onDragStartSegment = useCallback((id: string) => {
    dragId.current = id;
  }, []);

  const onDragOverSegment = useCallback((id: string) => {
    setDragOverId((prev) => (prev === id ? prev : id));
  }, []);

  const onDropSegment = useCallback((targetId: string) => {
    const sourceId = dragId.current;
    dragId.current = null;
    setDragOverId(null);
    if (!sourceId || sourceId === targetId) return;
    setSegments((prev) => {
      const targetIndex = prev.findIndex((s) => s.id === targetId);
      if (targetIndex < 0) return prev;
      return moveSegmentToIndex(prev, sourceId, targetIndex);
    });
  }, []);

  const onDragEndSegment = useCallback(() => {
    dragId.current = null;
    setDragOverId(null);
  }, []);

  const addSegment = useCallback(() => {
    setSegments((prev) => {
      const end = sourceDuration > 0 ? Number(sourceDuration.toFixed(3)) : 1;
      return [...prev, newSegment(0, end)];
    });
  }, [sourceDuration]);

  const updateOverlay = useCallback((id: string, patch: Partial<TextOverlay>) => {
    setOverlays((prev) => prev.map((o) => (o.id === id ? { ...o, ...patch } : o)));
  }, []);

  const removeOverlay = useCallback((id: string) => {
    setOverlays((prev) => prev.filter((o) => o.id !== id));
  }, []);

  const addOverlay = useCallback(() => {
    setOverlays((prev) => [...prev, newOverlay(timelineDuration(segments))]);
  }, [segments]);

  const setMusicTrack = useCallback((musicId: string) => {
    setMusic((prev) => ({ ...prev, musicId }));
  }, []);

  const setMusicVolume = useCallback((volume: number) => {
    setMusic((prev) => ({ ...prev, volume }));
  }, []);

  // --- Save (real timeline-export job) ------------------------------------- //
  const onSave = useCallback(async () => {
    if (!source) return;
    const validation = validateTimeline(segments, overlays, sourceDuration, music);
    if (validation) {
      setSaveError(validation);
      setSaveMessage("");
      return;
    }
    setSaving(true);
    setSaveError("");
    setSaveMessage("");
    try {
      const body = toTimelineExportBody(segments, overlays, music);
      const job = await createTimelineExport(source.jobId, body, {
        idempotencyKey: newIdempotencyKey(),
      });
      setSaveMessage(`Export queued as job ${job.job_id}.`);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setSaveError("Your session is not authorized. Sign in on the main app first.");
      } else {
        setSaveError(errorMessage(error, "Could not queue the export. Try again."));
      }
    } finally {
      setSaving(false);
    }
  }, [source, segments, overlays, sourceDuration, music]);

  const outputDuration = timelineDuration(segments);
  const validationHint =
    loadState === "loaded"
      ? validateTimeline(segments, overlays, sourceDuration, music)
      : null;

  return (
    <main style={styles.page}>
      <header style={styles.header}>
        <h1 style={styles.title}>Reel Editor</h1>
        <div style={styles.loadRow}>
          <Input
            value={jobId}
            placeholder="Reel job id"
            onChange={(e) => setJobId(e.target.value)}
            aria-label="Reel job id"
          />
          <Button onClick={onLoadClick} disabled={loadState === "loading"}>
            {loadState === "loading" ? "Loading…" : "Load reel"}
          </Button>
        </div>
        {loadState === "loading" && source && !source.terminal ? (
          <p style={styles.muted}>Rendering… {Math.round((source.progress || 0))}%</p>
        ) : null}
        {loadState === "error" ? <p style={styles.error}>{loadError}</p> : null}
      </header>

      {loadState === "loaded" && source ? (
        <section style={styles.grid}>
          <div style={styles.previewCol}>
            <video
              ref={videoRef}
              src={source.resultUrl}
              poster={source.posterUrl}
              controls
              onLoadedMetadata={onVideoMetadata}
              style={styles.video}
            />
            <p style={styles.muted}>
              Source {formatTimecode(sourceDuration)} · Output {formatTimecode(outputDuration)}
            </p>
          </div>

          <div style={styles.editCol}>
            <div style={styles.sectionHead}>
              <h2 style={styles.sectionTitle}>Clips</h2>
              <Button variant="outline" size="sm" onClick={addSegment}>
                Add clip
              </Button>
            </div>
            {segments.map((seg, index) => (
              <SegmentRow
                key={seg.id}
                segment={seg}
                index={index}
                total={segments.length}
                dragOver={dragOverId === seg.id}
                onChange={updateSegment}
                onMove={reorder}
                onRemove={removeSegment}
                onDragStart={onDragStartSegment}
                onDragOver={onDragOverSegment}
                onDrop={onDropSegment}
                onDragEnd={onDragEndSegment}
              />
            ))}

            <div style={styles.sectionHead}>
              <h2 style={styles.sectionTitle}>Text overlays</h2>
              <Button variant="outline" size="sm" onClick={addOverlay}>
                Add overlay
              </Button>
            </div>
            {overlays.map((ov, index) => (
              <OverlayRow
                key={ov.id}
                overlay={ov}
                index={index}
                onChange={updateOverlay}
                onRemove={removeOverlay}
              />
            ))}

            <div style={styles.sectionHead}>
              <h2 style={styles.sectionTitle}>Background music</h2>
            </div>
            <MusicRow
              music={music}
              tracks={musicTracks}
              onTrackChange={setMusicTrack}
              onVolumeChange={setMusicVolume}
            />

            <div style={styles.saveRow}>
              <Button onClick={onSave} disabled={saving || Boolean(validationHint)}>
                {saving ? "Saving…" : "Save export"}
              </Button>
              {validationHint ? <span style={styles.muted}>{validationHint}</span> : null}
            </div>
            {saveMessage ? <p style={styles.success}>{saveMessage}</p> : null}
            {saveError ? <p style={styles.error}>{saveError}</p> : null}
          </div>
        </section>
      ) : null}
    </main>
  );
}

interface SegmentRowProps {
  segment: TimelineSegment;
  index: number;
  total: number;
  dragOver: boolean;
  onChange: (id: string, patch: Partial<TimelineSegment>) => void;
  onMove: (id: string, direction: -1 | 1) => void;
  onRemove: (id: string) => void;
  onDragStart: (id: string) => void;
  onDragOver: (id: string) => void;
  onDrop: (id: string) => void;
  onDragEnd: () => void;
}

function SegmentRow({
  segment,
  index,
  total,
  dragOver,
  onChange,
  onMove,
  onRemove,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
}: SegmentRowProps) {
  return (
    <div
      style={dragOver ? { ...styles.row, ...styles.rowDragOver } : styles.row}
      draggable
      onDragStart={(e) => {
        e.dataTransfer.effectAllowed = "move";
        onDragStart(segment.id);
      }}
      onDragOver={(e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        onDragOver(segment.id);
      }}
      onDrop={(e) => {
        e.preventDefault();
        onDrop(segment.id);
      }}
      onDragEnd={onDragEnd}
    >
      <div style={styles.rowHead}>
        <strong style={styles.dragHandle} title="Drag to reorder">
          ⠿ Clip {index + 1}
        </strong>
        <div style={styles.rowActions}>
          <Button
            variant="ghost"
            size="sm"
            disabled={index === 0}
            onClick={() => onMove(segment.id, -1)}
            aria-label="Move clip up"
          >
            ↑
          </Button>
          <Button
            variant="ghost"
            size="sm"
            disabled={index === total - 1}
            onClick={() => onMove(segment.id, 1)}
            aria-label="Move clip down"
          >
            ↓
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onRemove(segment.id)}
            aria-label="Remove clip"
          >
            ✕
          </Button>
        </div>
      </div>
      <div style={styles.fields}>
        <NumberField
          label="In (s)"
          value={segment.sourceIn}
          step={0.1}
          onChange={(v) => onChange(segment.id, { sourceIn: v })}
        />
        <NumberField
          label="Out (s)"
          value={segment.sourceOut}
          step={0.1}
          onChange={(v) => onChange(segment.id, { sourceOut: v })}
        />
        <NumberField
          label="Speed"
          value={segment.speed}
          step={0.05}
          min={MIN_SPEED}
          max={MAX_SPEED}
          onChange={(v) => onChange(segment.id, { speed: v })}
        />
      </div>
      <Input
        value={segment.caption}
        placeholder="Caption (optional)"
        onChange={(e) => onChange(segment.id, { caption: e.target.value })}
        aria-label={`Clip ${index + 1} caption`}
      />
    </div>
  );
}

interface OverlayRowProps {
  overlay: TextOverlay;
  index: number;
  onChange: (id: string, patch: Partial<TextOverlay>) => void;
  onRemove: (id: string) => void;
}

function OverlayRow({ overlay, index, onChange, onRemove }: OverlayRowProps) {
  return (
    <div style={styles.row}>
      <div style={styles.rowHead}>
        <strong>Overlay {index + 1}</strong>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onRemove(overlay.id)}
          aria-label="Remove overlay"
        >
          ✕
        </Button>
      </div>
      <Textarea
        value={overlay.text}
        placeholder="Overlay text"
        onChange={(e) => onChange(overlay.id, { text: e.target.value })}
        aria-label={`Overlay ${index + 1} text`}
      />
      <div style={styles.fields}>
        <NumberField
          label="Start (s)"
          value={overlay.startS}
          step={0.1}
          onChange={(v) => onChange(overlay.id, { startS: v })}
        />
        <NumberField
          label="End (s)"
          value={overlay.endS}
          step={0.1}
          onChange={(v) => onChange(overlay.id, { endS: v })}
        />
        <label style={styles.field}>
          <span style={styles.fieldLabel}>Position</span>
          <NativeSelect
            value={overlay.position}
            onChange={(e) =>
              onChange(overlay.id, { position: e.target.value as OverlayPosition })
            }
          >
            <NativeSelectOption value="top">Top</NativeSelectOption>
            <NativeSelectOption value="center">Center</NativeSelectOption>
            <NativeSelectOption value="bottom">Bottom</NativeSelectOption>
          </NativeSelect>
        </label>
      </div>
    </div>
  );
}

interface MusicRowProps {
  music: MusicSelection;
  tracks: MusicTrack[];
  onTrackChange: (musicId: string) => void;
  onVolumeChange: (volume: number) => void;
}

function MusicRow({ music, tracks, onTrackChange, onVolumeChange }: MusicRowProps) {
  const hasSelection = Boolean(music.musicId);
  return (
    <div style={styles.row}>
      <div style={styles.fields}>
        <label style={styles.field}>
          <span style={styles.fieldLabel}>Track</span>
          <NativeSelect
            value={music.musicId}
            onChange={(e) => onTrackChange(e.target.value)}
            aria-label="Background music track"
          >
            <NativeSelectOption value="">None</NativeSelectOption>
            {tracks.map((track) => (
              <NativeSelectOption key={track.id} value={track.id}>
                {track.name}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </label>
        <NumberField
          label="Volume"
          value={music.volume}
          step={0.05}
          min={MIN_MUSIC_VOLUME}
          max={MAX_MUSIC_VOLUME}
          onChange={onVolumeChange}
        />
      </div>
      {tracks.length === 0 ? (
        <span style={styles.muted}>No music tracks are available in this deployment.</span>
      ) : hasSelection ? (
        <span style={styles.muted}>
          Mixed under the reel audio at {music.volume.toFixed(2)}× gain.
        </span>
      ) : (
        <span style={styles.muted}>Optional — adds a looped background track under the video.</span>
      )}
    </div>
  );
}

interface NumberFieldProps {
  label: string;
  value: number;
  step?: number;
  min?: number;
  max?: number;
  onChange: (value: number) => void;
}

function NumberField({ label, value, step, min, max, onChange }: NumberFieldProps) {
  return (
    <label style={styles.field}>
      <span style={styles.fieldLabel}>{label}</span>
      <Input
        type="number"
        value={Number.isFinite(value) ? value : 0}
        step={step}
        min={min}
        max={max}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label={label}
      />
    </label>
  );
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    function onAbort() {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    }
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

const styles: Record<string, CSSProperties> = {
  page: { maxWidth: 1100, margin: "0 auto", padding: 24, fontFamily: "system-ui, sans-serif" },
  header: { display: "flex", flexDirection: "column", gap: 8, marginBottom: 24 },
  title: { fontSize: 24, fontWeight: 700, margin: 0 },
  loadRow: { display: "flex", gap: 8, alignItems: "center" },
  grid: { display: "grid", gridTemplateColumns: "minmax(240px, 360px) 1fr", gap: 24 },
  previewCol: { display: "flex", flexDirection: "column", gap: 8 },
  video: { width: "100%", borderRadius: 8, background: "#000", aspectRatio: "9 / 16" },
  editCol: { display: "flex", flexDirection: "column", gap: 12 },
  sectionHead: { display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 8 },
  sectionTitle: { fontSize: 16, fontWeight: 600, margin: 0 },
  row: { display: "flex", flexDirection: "column", gap: 8, padding: 12, border: "1px solid #e2e2e2", borderRadius: 8 },
  rowDragOver: { border: "1px dashed #1a7f37", background: "#f0fbf3" },
  dragHandle: { cursor: "grab", userSelect: "none" },
  rowHead: { display: "flex", justifyContent: "space-between", alignItems: "center" },
  rowActions: { display: "flex", gap: 4 },
  fields: { display: "flex", gap: 8, flexWrap: "wrap" },
  field: { display: "flex", flexDirection: "column", gap: 4, minWidth: 90 },
  fieldLabel: { fontSize: 12, color: "#666" },
  saveRow: { display: "flex", gap: 12, alignItems: "center", marginTop: 12 },
  muted: { color: "#666", fontSize: 13, margin: 0 },
  error: { color: "#c0362c", fontSize: 14, margin: 0 },
  success: { color: "#1a7f37", fontSize: 14, margin: 0 },
};
