"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Download, Loader2, RefreshCw, Square, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorText, errorMessage, useRequestOptions } from "@/src/features/ad-studio/shared";
import { POLL_INTERVAL_MS } from "@/src/shared/api";
import {
  KIND_LABELS,
  cancelCapture,
  deleteCapture,
  formatSeconds,
  getCapture,
  isActive,
  retryCapture,
  type CaptureDetail,
} from "./api";
import { StatusBadge } from "./CaptureList";
import { MakeAdsPanel } from "./MakeAdsPanel";

function ListingFacts({ listing }: { listing: Record<string, unknown> }) {
  const facts: [string, string][] = [];
  const add = (label: string, value: unknown) => {
    if (value !== null && value !== undefined && String(value).trim()) facts.push([label, String(value)]);
  };
  add("Developer", listing.developer);
  add("Genre", listing.genre);
  add("Price", listing.price_label);
  add("Rating", typeof listing.rating === "number" ? `${listing.rating} / 5` : null);
  if (facts.length === 0) return null;
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4">
      {facts.map(([k, v]) => (
        <div key={k}>
          <dt className="text-xs text-muted-foreground">{k}</dt>
          <dd className="font-medium">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/** One capture: live status, recorded videos, screenshots and ad making. */
export function CaptureDetailView({ captureId }: { captureId: string }) {
  const router = useRouter();
  const requestOptions = useRequestOptions();
  const [capture, setCapture] = React.useState<CaptureDetail | null>(null);
  const [notFound, setNotFound] = React.useState(false);
  const [busy, setBusy] = React.useState<"" | "retry" | "cancel" | "delete">("");
  const [error, setError] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      setCapture(await getCapture(captureId, await requestOptions()));
      setError("");
    } catch (err) {
      const status = (err as { status?: number }).status;
      if (status === 404) setNotFound(true);
      else setError(errorMessage(err));
    }
  }, [captureId, requestOptions]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const active = capture ? isActive(capture.status) : false;
  React.useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => void load(), POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [active, load]);

  const act = async (kind: "retry" | "cancel" | "delete") => {
    setBusy(kind);
    setError("");
    try {
      const opts = await requestOptions();
      if (kind === "delete") {
        await deleteCapture(captureId, opts);
        router.push("/capture");
        return;
      }
      if (kind === "retry") await retryCapture(captureId, opts);
      else await cancelCapture(captureId, opts);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  };

  const back = (
    <Link href="/capture" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
      <ArrowLeft className="h-4 w-4" aria-hidden /> All captures
    </Link>
  );

  if (notFound) {
    return (
      <div className="space-y-4">
        {back}
        <p className="text-sm text-muted-foreground">This capture does not exist or was deleted.</p>
      </div>
    );
  }
  if (!capture) {
    return (
      <div className="space-y-4">
        {back}
        <ErrorText message={error} />
        <Skeleton className="h-10 w-2/3" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  const isLegacyWebGame = capture.source_kind === "web_game";
  const isWebLink = /^https?:\/\//i.test(capture.source_url);

  return (
    <div className="space-y-6">
      {back}
      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={capture.status} />
          <span className="text-sm text-muted-foreground">{KIND_LABELS[capture.source_kind]}</span>
        </div>
        <h1 className="break-words text-2xl font-semibold">{capture.title || capture.source_url}</h1>
        {isWebLink ? (
          <a
            href={capture.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="break-all text-sm text-muted-foreground underline"
          >
            {capture.source_url}
          </a>
        ) : (
          <p className="break-all font-mono text-xs text-muted-foreground">{capture.source_url}</p>
        )}
      </header>

      {active ? (
        <Card>
          <CardContent className="space-y-3 p-5">
            <p className="text-sm">
              {capture.status === "queued" ? "Waiting for a free recorder..." : "Recording and encoding. This usually takes a minute or two per format."}
            </p>
            <Progress value={capture.progress} />
            <Button variant="outline" size="sm" onClick={() => act("cancel")} disabled={busy !== ""}>
              {busy === "cancel" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden /> : <Square className="mr-2 h-4 w-4" aria-hidden />}
              Cancel
            </Button>
          </CardContent>
        </Card>
      ) : null}

      {capture.status === "failed" || capture.status === "canceled" ? (
        <Card>
          <CardContent className="space-y-3 p-5">
            <p className="text-sm text-destructive">{capture.error || "The capture did not finish."}</p>
            <div className="flex gap-2">
              <Button size="sm" onClick={() => act("retry")} disabled={busy !== "" || isLegacyWebGame}>
                {busy === "retry" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden /> : <RefreshCw className="mr-2 h-4 w-4" aria-hidden />}
                Retry
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      <ErrorText message={error} />

      {capture.listing ? <ListingFacts listing={capture.listing} /> : null}

      {capture.outputs.length > 0 ? (
        <section aria-labelledby="outputs-heading" className="space-y-3">
          <h2 id="outputs-heading" className="text-lg font-semibold">
            Recorded video
          </h2>
          {isLegacyWebGame ? (
            <p className="text-sm text-muted-foreground">
              This is an older web game capture. Web game capture was retired; new game captures record the mobile
              game from a simulator.
            </p>
          ) : null}
          <div className="flex flex-wrap items-start gap-4">
            {capture.outputs.map((o) => (
              <figure key={o.aspect} className={o.aspect === "9:16" ? "w-56" : "w-full max-w-xl"}>
                {o.video_url ? (
                  <video
                    src={o.video_url}
                    poster={o.poster_url ?? undefined}
                    controls
                    playsInline
                    preload="metadata"
                    className="w-full rounded-lg border bg-black"
                  />
                ) : (
                  <div className="flex aspect-video items-center justify-center rounded-lg border text-sm text-muted-foreground">
                    Preview unavailable
                  </div>
                )}
                <figcaption className="mt-2 flex items-center justify-between text-sm">
                  <span>
                    {o.aspect} · {formatSeconds(o.duration_ms)}
                  </span>
                  {o.download_url ? (
                    <a href={o.download_url} className="inline-flex items-center gap-1 underline">
                      <Download className="h-3.5 w-3.5" aria-hidden /> Download
                    </a>
                  ) : null}
                </figcaption>
              </figure>
            ))}
          </div>
        </section>
      ) : null}

      {capture.screenshots.length > 0 ? (
        <section aria-labelledby="shots-heading" className="space-y-3">
          <h2 id="shots-heading" className="text-lg font-semibold">
            Screenshots
          </h2>
          <ul className="flex flex-wrap gap-3">
            {capture.screenshots.map((s) =>
              s.url ? (
                <li key={s.key}>
                  <a href={s.url} target="_blank" rel="noopener noreferrer">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={s.url} alt={s.label} className="h-40 w-auto rounded border object-contain" />
                  </a>
                </li>
              ) : null,
            )}
          </ul>
        </section>
      ) : null}

      {capture.status === "succeeded" && capture.outputs.length > 0 ? <MakeAdsPanel capture={capture} /> : null}

      {!active ? (
        <div className="border-t pt-4">
          <Button variant="ghost" size="sm" onClick={() => act("delete")} disabled={busy !== ""}>
            {busy === "delete" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden /> : <Trash2 className="mr-2 h-4 w-4" aria-hidden />}
            Delete capture
          </Button>
          <p className="mt-1 text-xs text-muted-foreground">Recorded videos stay in your media library.</p>
        </div>
      ) : null}
    </div>
  );
}
