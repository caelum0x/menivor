"use client";

import * as React from "react";
import { Copy, Download, FileText, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { exportAdProject, type ExportManifest } from "./api";
import { ErrorText, errorMessage, useRequestOptions } from "./shared";

function csvCell(value: string): string {
  return `"${value.replace(/"/g, '""')}"`;
}

export function manifestCsv(manifest: ExportManifest): string {
  const header = ["filename", "format", "aspect", "angle", "post_caption", "script"].join(",");
  const rows = manifest.items.map((i) =>
    [i.filename, i.format, i.aspect, i.angle_label, i.post_caption, i.script].map(csvCell).join(","),
  );
  return [header, ...rows].join("\n");
}

function saveBlob(content: string, filename: string, type: string): void {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** Batch export: every finished ad plus a captions sheet for posting. */
export function ExportPanel({ projectId, readyCount }: { projectId: string; readyCount: number }) {
  const requestOptions = useRequestOptions();
  const [busy, setBusy] = React.useState<"" | "videos" | "sheet" | "copy">("");
  const [error, setError] = React.useState("");
  const [note, setNote] = React.useState("");

  const load = async () => exportAdProject(projectId, await requestOptions());

  const downloadAll = async () => {
    setBusy("videos");
    setError("");
    setNote("");
    try {
      const manifest = await load();
      for (const item of manifest.items) {
        const a = document.createElement("a");
        a.href = item.download_url;
        a.download = item.filename;
        a.rel = "noopener";
        document.body.appendChild(a);
        a.click();
        a.remove();
        // Browsers drop rapid back-to-back downloads; pace them.
        await wait(700);
      }
      setNote(
        `${manifest.items.length} video${manifest.items.length === 1 ? "" : "s"} downloading` +
          (manifest.pending ? `; ${manifest.pending} still rendering` : "") +
          ". Allow multiple downloads if your browser asks.",
      );
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  };

  const downloadSheet = async () => {
    setBusy("sheet");
    setError("");
    try {
      const manifest = await load();
      saveBlob(manifestCsv(manifest), `${projectId}-ads.csv`, "text/csv;charset=utf-8");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  };

  const copyCaptions = async () => {
    setBusy("copy");
    setError("");
    try {
      const manifest = await load();
      const text = manifest.items.map((i) => `${i.filename}\n${i.post_caption}`).join("\n\n");
      await navigator.clipboard.writeText(text);
      setNote("Post captions copied.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  };

  return (
    <Card>
      <CardContent className="flex flex-wrap items-center justify-between gap-3 p-4">
        <div>
          <p className="font-medium">Batch export</p>
          <p className="text-sm text-muted-foreground">
            {readyCount} finished ad{readyCount === 1 ? "" : "s"}. Videos are also saved to your uploads library.
          </p>
          {note ? <p className="mt-1 text-sm text-muted-foreground">{note}</p> : null}
          <ErrorText message={error} />
        </div>
        <div className="flex flex-wrap gap-2">
          <Button onClick={downloadAll} disabled={busy !== "" || readyCount === 0}>
            {busy === "videos" ? <Loader2 className="animate-spin" aria-hidden /> : <Download aria-hidden />} Download all
          </Button>
          <Button variant="outline" onClick={downloadSheet} disabled={busy !== "" || readyCount === 0}>
            <FileText aria-hidden /> Captions sheet (CSV)
          </Button>
          <Button variant="outline" onClick={copyCaptions} disabled={busy !== "" || readyCount === 0}>
            <Copy aria-hidden /> Copy captions
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
