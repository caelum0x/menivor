"use client";

import * as React from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Copy,
  Download,
  ExternalLink,
  LoaderCircle,
  Pause,
  Play,
  RotateCcw,
  Scissors,
} from "lucide-react";
import { useTranslations } from "@/lib/i18n/context";
import { mapJobToEditorSource, formatTimecode, normalizeCutRange } from "./model";
import { useEditorJob } from "./use-editor-job";
import { useEditorExport } from "./use-editor-export";
import { TimelineEditor } from "./TimelineEditor";
import { ReelPicker } from "@/src/features/reels-library/components/ReelPicker";

const CUT_STORAGE_PREFIX = "menivor.editor.cut.";

/** Last cut the user made on this reel, so a refresh resumes the edit. */
function readSavedCut(jobId: string): { inPoint: number; outPoint: number } | null {
  if (typeof window === "undefined" || !jobId) return null;
  try {
    const raw = window.localStorage.getItem(`${CUT_STORAGE_PREFIX}${jobId}`);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { inPoint?: unknown; outPoint?: unknown };
    if (typeof parsed.inPoint !== "number" || typeof parsed.outPoint !== "number") return null;
    return { inPoint: parsed.inPoint, outPoint: parsed.outPoint };
  } catch {
    return null;
  }
}

function writeSavedCut(jobId: string, inPoint: number, outPoint: number): void {
  if (typeof window === "undefined" || !jobId) return;
  try {
    window.localStorage.setItem(
      `${CUT_STORAGE_PREFIX}${jobId}`,
      JSON.stringify({ inPoint, outPoint }),
    );
  } catch {
    // Storage full or disabled: the edit still works, it just won't resume.
  }
}

export function EditorWorkspace({ jobId }: Readonly<{ jobId: string }>) {
  const t = useTranslations();
  const jobState = useEditorJob(jobId);
  const videoRef = React.useRef<HTMLVideoElement>(null);
  const [mediaDuration, setMediaDuration] = React.useState(0);
  const [inPoint, setInPoint] = React.useState(0);
  const [outPoint, setOutPoint] = React.useState(0);
  const [currentTime, setCurrentTime] = React.useState(0);
  const [playing, setPlaying] = React.useState(false);
  const [copied, setCopied] = React.useState(false);
  const [mediaSourceJobId, setMediaSourceJobId] = React.useState("");

  const source = jobState.job ? mapJobToEditorSource(jobState.job) : null;
  const exportState = useEditorExport(source?.jobId ?? "");
  const exportedSource = exportState.exportJob.job
    ? mapJobToEditorSource(exportState.exportJob.job)
    : null;
  const cut = normalizeCutRange(inPoint, outPoint || mediaDuration, mediaDuration);
  const playheadPct = mediaDuration > 0 ? (currentTime / mediaDuration) * 100 : 0;
  const inPct = mediaDuration > 0 ? (cut.inPoint / mediaDuration) * 100 : 0;
  const outPct = mediaDuration > 0 ? (cut.outPoint / mediaDuration) * 100 : 100;

  React.useEffect(() => {
    setMediaDuration(0);
    setInPoint(0);
    setOutPoint(0);
    setCurrentTime(0);
    setPlaying(false);
    setMediaSourceJobId("");
  }, [source?.jobId]);

  React.useEffect(() => {
    if (!source?.jobId || mediaSourceJobId !== source.jobId || mediaDuration <= 0) return;
    writeSavedCut(source.jobId, cut.inPoint, cut.outPoint);
  }, [cut.inPoint, cut.outPoint, mediaDuration, mediaSourceJobId, source?.jobId]);

  const seek = React.useCallback((time: number) => {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = Math.min(Math.max(0, time), mediaDuration);
    setCurrentTime(video.currentTime);
  }, [mediaDuration]);

  const playSelection = React.useCallback(async () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.currentTime < cut.inPoint || video.currentTime >= cut.outPoint) {
      video.currentTime = cut.inPoint;
    }
    await video.play();
  }, [cut.inPoint, cut.outPoint]);

  const togglePlayback = React.useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) void playSelection();
    else video.pause();
  }, [playSelection]);

  const copyCut = React.useCallback(async () => {
    await navigator.clipboard.writeText(
      `job=${jobId} in=${cut.inPoint.toFixed(2)}s out=${cut.outPoint.toFixed(2)}s`,
    );
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }, [cut.inPoint, cut.outPoint, jobId]);

  if (!jobId) return <NoSource />;
  if ((jobState.status === "loading" || jobState.status === "idle") && !source) {
    return (
      <WorkspaceMessage
        title={t("editor.loadingTitle")}
        detail={t("editor.jobLabel", { id: jobId })}
      />
    );
  }
  if (jobState.status === "error" && !source) {
    return (
      <WorkspaceMessage
        title={t("editor.loadErrorTitle")}
        detail={jobState.error}
      />
    );
  }
  if (!source) return <NoSource />;
  if (!source.terminal || source.failed || !source.resultUrl) {
    return (
      <WorkspaceMessage
        title={source.failed ? t("editor.renderFailedTitle") : t("editor.renderNotReadyTitle")}
        detail={source.error || `Current progress: ${source.progress}%`}
        href={`/jobs/${source.jobId}`}
      />
    );
  }

  return (
    <main className="min-h-dvh bg-[#000000] font-mono text-white">
      <header className="flex min-h-14 items-center justify-between border-b border-[#292929] px-4 md:px-6">
        <div className="flex min-w-0 items-center gap-4">
          <Link href={`/jobs/${source.jobId}`} className="text-[#A3A3A3] hover:text-white" aria-label={t("editor.backAria")}>
            <ArrowLeft className="size-4" aria-hidden />
          </Link>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold">{t("editor.title")}</p>
            <p className="truncate text-xs text-[#8A8A8A]">{source.jobId}</p>
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs tabular-nums text-[#A3A3A3]">
          <span>{formatTimecode(currentTime)}</span>
          <span>/</span>
          <span>{formatTimecode(mediaDuration)}</span>
        </div>
      </header>

      <div className="grid min-h-[calc(100dvh-3.5rem)] grid-cols-1 lg:grid-cols-[minmax(0,1fr)_320px]">
        <section className="relative flex min-h-[58dvh] items-center justify-center border-b border-[#292929] bg-[#0B0C0A] p-5 lg:border-b-0 lg:border-r">
          <div className="relative max-h-[70dvh] w-full max-w-[390px] border border-[#292929] bg-black">
            <video
              key={source.jobId}
              ref={videoRef}
              src={source.resultUrl}
              poster={source.posterUrl}
              playsInline
              preload="metadata"
              className="aspect-[9/16] max-h-[70dvh] w-full bg-black object-contain"
              onLoadedMetadata={(event) => {
                const duration = event.currentTarget.duration;
                const saved = readSavedCut(source.jobId);
                const restored = saved
                  ? normalizeCutRange(saved.inPoint, saved.outPoint, duration)
                  : null;
                setMediaDuration(duration);
                setInPoint(restored ? restored.inPoint : 0);
                setOutPoint(restored ? restored.outPoint : duration);
                setMediaSourceJobId(source.jobId);
              }}
              onTimeUpdate={(event) => {
                const time = event.currentTarget.currentTime;
                setCurrentTime(time);
                if (time >= cut.outPoint) {
                  event.currentTarget.pause();
                  event.currentTarget.currentTime = cut.inPoint;
                  setCurrentTime(cut.inPoint);
                }
              }}
              onPlay={() => setPlaying(true)}
              onPause={() => setPlaying(false)}
            />
            <button
              type="button"
              onClick={togglePlayback}
              className="absolute inset-0 flex items-center justify-center bg-transparent text-white opacity-0 transition-opacity hover:bg-black/20 hover:opacity-100 focus:opacity-100"
              aria-label={playing ? t("editor.pauseAria") : t("editor.playAria")}
            >
              {playing ? <Pause className="size-10" aria-hidden /> : <Play className="size-10" aria-hidden />}
            </button>
          </div>
        </section>

        <aside className="flex flex-col bg-[#000000]">
          <div className="border-b border-[#292929] p-5">
            <h1 className="text-sm font-semibold">{t("editor.cutRangeHeading")}</h1>
            <p className="mt-2 text-xs leading-5 text-[#8A8A8A]">
              {t("editor.cutRangeHelp")}
            </p>
          </div>

          <div className="space-y-6 p-5">
            <TimeControl
              label={t("editor.inPoint")}
              value={cut.inPoint}
              max={Math.max(0, cut.outPoint - 0.1)}
              onChange={(value) => {
                setInPoint(value);
                seek(value);
              }}
            />
            <TimeControl
              label={t("editor.outPoint")}
              value={cut.outPoint}
              min={Math.min(mediaDuration, cut.inPoint + 0.1)}
              max={mediaDuration}
              onChange={(value) => {
                setOutPoint(value);
                seek(value);
              }}
            />

            <div className="grid grid-cols-2 border border-[#292929] text-xs tabular-nums">
              <div className="border-r border-[#292929] p-3">
                <p className="text-[#777777]">{t("editor.selected")}</p>
                <p className="mt-1 text-[#C6FF4A]">{formatTimecode(cut.duration)}</p>
              </div>
              <div className="p-3">
                <p className="text-[#777777]">{t("editor.source")}</p>
                <p className="mt-1">{formatTimecode(mediaDuration)}</p>
              </div>
            </div>

            <div className="grid gap-2">
              <IndustrialButton onClick={() => void playSelection()} primary>
                <Play className="size-4" aria-hidden /> {t("editor.previewCut")}
              </IndustrialButton>
              <IndustrialButton onClick={() => {
                setInPoint(0);
                setOutPoint(mediaDuration);
                seek(0);
              }}>
                <RotateCcw className="size-4" aria-hidden /> {t("editor.resetRange")}
              </IndustrialButton>
              <IndustrialButton onClick={() => void copyCut()}>
                <Copy className="size-4" aria-hidden /> {copied ? t("editor.copied") : t("editor.copyCutValues")}
              </IndustrialButton>
              <IndustrialButton
                onClick={() => void exportState.submit(cut)}
                primary
                disabled={exportState.submitting || mediaDuration <= 0}
              >
                {exportState.submitting ? (
                  <LoaderCircle className="size-4 animate-spin" aria-hidden />
                ) : (
                  <Scissors className="size-4" aria-hidden />
                )}
                {exportState.submitting ? t("editor.queuingExport") : t("editor.exportSelection")}
              </IndustrialButton>
              {exportState.exportJobId && !exportedSource?.terminal && (
                <div className="border border-[#292929] p-3 text-xs text-[#A3A3A3]">
                  Export {exportedSource?.progress ?? 0}% · {exportState.exportJobId.slice(0, 12)}
                </div>
              )}
              {exportedSource?.failed && (
                <div role="alert" className="border border-red-900 bg-red-950/30 p-3 text-xs text-red-300">
                  {exportedSource.error || t("editor.exportFailedFallback")}
                </div>
              )}
              {exportState.error && (
                <div role="alert" className="border border-red-900 bg-red-950/30 p-3 text-xs text-red-300">
                  {exportState.error}
                </div>
              )}
              {exportedSource?.terminal && !exportedSource.failed && exportedSource.resultUrl && (
                <a
                  href={exportedSource.resultUrl}
                  download
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex h-10 items-center justify-center gap-2 border border-[#C6FF4A] text-xs text-[#C6FF4A] hover:bg-[#C6FF4A] hover:text-black"
                >
                  <Download className="size-4" aria-hidden /> {t("editor.downloadExportedCut")}
                </a>
              )}
              {exportedSource?.terminal && !exportedSource.failed && exportState.exportJobId && (
                <Link
                  href={`/jobs/${encodeURIComponent(exportState.exportJobId)}`}
                  className="flex h-10 items-center justify-center gap-2 border border-[#292929] text-xs hover:border-white"
                >
                  <ExternalLink className="size-4" aria-hidden /> {t("editor.openExportedReel")}
                </Link>
              )}
              <a
                href={source.resultUrl}
                download
                target="_blank"
                rel="noopener noreferrer"
                className="flex h-10 items-center justify-center gap-2 border border-[#292929] text-xs hover:border-white"
              >
                <Download className="size-4" aria-hidden /> {t("editor.downloadSource")}
              </a>
            </div>
          </div>

          {source.correlationId && (
            <div className="mt-auto border-t border-[#292929] p-5 text-[11px] text-[#686868]">
              Correlation {source.correlationId}
            </div>
          )}
        </aside>
      </div>

      <section className="border-t border-[#292929] bg-[#0B0C0A] px-4 py-5 md:px-6">
        <div className="mb-3 flex items-center justify-between text-xs tabular-nums">
          <span>{t("editor.timeline")}</span>
          <span className="text-[#8A8A8A]">{formatTimecode(cut.inPoint)} — {formatTimecode(cut.outPoint)}</span>
        </div>
        <button
          type="button"
          className="relative h-20 w-full overflow-hidden border border-[#292929] bg-[#111111] text-left"
          onClick={(event) => {
            const bounds = event.currentTarget.getBoundingClientRect();
            seek(((event.clientX - bounds.left) / bounds.width) * mediaDuration);
          }}
          aria-label={t("editor.seekAria")}
        >
          <span className="absolute inset-y-0 bg-black/70" style={{ width: `${inPct}%` }} />
          <span className="absolute inset-y-0 right-0 bg-black/70" style={{ width: `${100 - outPct}%` }} />
          <span className="absolute inset-y-0 border-x border-[#C6FF4A] bg-[#C6FF4A]/10" style={{ left: `${inPct}%`, width: `${Math.max(0, outPct - inPct)}%` }} />
          <span className="absolute inset-y-0 w-px bg-[#C6FF4A]" style={{ left: `${playheadPct}%` }} />
          <span className="absolute left-3 top-3 flex items-center gap-2 text-xs text-[#A3A3A3]">
            <Scissors className="size-4 text-[#C6FF4A]" aria-hidden /> {source.jobId.slice(0, 12)}
          </span>
        </button>
      </section>

      <section className="border-t border-[#292929] bg-[#0B0C0A] px-4 py-6 md:px-6">
        <p className="mb-3 text-xs uppercase tracking-wide text-[#8A8A8A]">
          {t("editor.advancedHeading")}
        </p>
        {mediaSourceJobId === source.jobId && mediaDuration > 0 ? (
          <TimelineEditor
            key={source.jobId}
            sourceJobId={source.jobId}
            sourceDuration={mediaDuration}
            initialIn={cut.inPoint}
            initialOut={cut.outPoint}
          />
        ) : (
          <p role="status" className="text-sm text-[#8A8A8A]">
            {t("editor.loadingDuration")}
          </p>
        )}
      </section>
    </main>
  );
}

function TimeControl({ label, value, min = 0, max, onChange }: Readonly<{
  label: string;
  value: number;
  min?: number;
  max: number;
  onChange: (value: number) => void;
}>) {
  return (
    <label className="block text-xs">
      <span className="mb-2 flex items-center justify-between">
        <span>{label}</span>
        <span className="tabular-nums text-[#C6FF4A]">{formatTimecode(value)}</span>
      </span>
      <input
        type="range"
        min={min}
        max={Math.max(min, max)}
        step="0.05"
        value={Math.min(Math.max(value, min), Math.max(min, max))}
        onChange={(event) => onChange(Number(event.target.value))}
        className="h-1 w-full cursor-ew-resize accent-[#C6FF4A]"
      />
    </label>
  );
}

function IndustrialButton({ children, onClick, primary = false, disabled = false }: Readonly<{
  children: React.ReactNode;
  onClick: () => void;
  primary?: boolean;
  disabled?: boolean;
}>) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={primary
        ? "flex h-10 items-center justify-center gap-2 border border-[#C6FF4A] bg-[#C6FF4A] text-xs font-semibold text-black hover:bg-black hover:text-[#C6FF4A] disabled:cursor-not-allowed disabled:opacity-40"
        : "flex h-10 items-center justify-center gap-2 border border-[#292929] text-xs hover:border-white disabled:cursor-not-allowed disabled:opacity-40"}
    >
      {children}
    </button>
  );
}

function NoSource() {
  const t = useTranslations();
  return (
    <main className="flex min-h-dvh items-center justify-center bg-[#000000] p-6 font-mono text-white">
      <div className="w-full max-w-2xl border border-[#292929] bg-[#0B0C0A] p-6">
        <Link href="/reels" className="mb-4 inline-flex items-center gap-2 text-xs text-[#8A8A8A] hover:text-white">
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> {t("editor.openLibrary")}
        </Link>
        <h1 className="text-xl font-semibold">{t("editor.noSourceTitle")}</h1>
        <p className="mt-3 text-sm leading-6 text-[#8A8A8A]">{t("editor.noSourceDetail")}</p>
        <div className="mt-6">
          <ReelPicker hrefFor={(id) => `/editor?job=${encodeURIComponent(id)}`} />
        </div>
      </div>
    </main>
  );
}

function WorkspaceMessage({ title, detail, href }: Readonly<{ title: string; detail: string; href?: string }>) {
  const t = useTranslations();
  return (
    <main className="flex min-h-dvh items-center justify-center bg-[#000000] p-6 font-mono text-white">
      <div className="w-full max-w-xl border border-[#292929] bg-[#0B0C0A] p-6">
        <h1 className="text-xl font-semibold">{title}</h1>
        <p className="mt-3 text-sm leading-6 text-[#8A8A8A]">{detail}</p>
        {href && <Link href={href} className="mt-6 inline-flex border-b border-[#C6FF4A] pb-1 text-sm text-[#C6FF4A]">{t("editor.openJobs")}</Link>}
      </div>
    </main>
  );
}
