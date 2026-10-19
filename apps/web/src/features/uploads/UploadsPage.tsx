"use client";

import * as React from "react";
import Link from "next/link";
import { useAuth } from "@/components/auth/clerk-safe";
import {
  AlertTriangle,
  Download,
  File as FileIcon,
  FileAudio,
  FileImage,
  FileVideo,
  FolderUp,
  Loader2,
  RefreshCw,
  Trash2,
  Upload,
} from "lucide-react";
import {
  ApiError,
  deleteUpload,
  listUploads,
  presignAndUpload,
  type UploadAsset,
  type UploadKind,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

type LoadState = "loading" | "ready" | "error";
type KindFilter = "all" | UploadKind;

const PAGE_SIZE = 60;
const ACCEPT = "video/*,image/*,audio/*";

const FILTERS: readonly { value: KindFilter; label: string }[] = [
  { value: "all", label: "All uploads" },
  { value: "video", label: "Videos" },
  { value: "image", label: "Images" },
  { value: "audio", label: "Audio" },
  { value: "upload", label: "Other files" },
];

const KIND_ICON: Record<UploadKind, React.ComponentType<{ className?: string }>> = {
  video: FileVideo,
  image: FileImage,
  audio: FileAudio,
  upload: FileIcon,
};

function messageOf(err: unknown, fallback: string): string {
  return friendlyErrorMessage(err, fallback);
}

function formatBytes(bytes?: number): string {
  if (!bytes || bytes <= 0) return "";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function formatDate(value?: string): string {
  if (!value) return "";
  const t = Date.parse(value);
  return Number.isNaN(t)
    ? ""
    : new Date(t).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

/**
 * Uploads library: every file the caller uploaded (source recordings,
 * voiceovers, avatar photos, b-roll references) with preview, download and
 * delete, plus a direct upload. Backed by GET/DELETE /uploads and the
 * presign → PUT → register upload flow.
 */
export function UploadsPage() {
  const { getToken, isLoaded } = useAuth();
  const [status, setStatus] = React.useState<LoadState>("loading");
  const [uploads, setUploads] = React.useState<readonly UploadAsset[]>([]);
  const [errorMessage, setErrorMessage] = React.useState("");
  const [filter, setFilter] = React.useState<KindFilter>("all");
  const [hasMore, setHasMore] = React.useState(false);
  const [nextOffset, setNextOffset] = React.useState(0);
  const [loadingMore, setLoadingMore] = React.useState(false);

  const [uploadProgress, setUploadProgress] = React.useState<number | null>(null);
  const [uploadError, setUploadError] = React.useState("");
  const [pendingIds, setPendingIds] = React.useState<ReadonlySet<string>>(new Set());
  const [rowErrors, setRowErrors] = React.useState<Readonly<Record<string, string>>>({});
  const fileInput = React.useRef<HTMLInputElement>(null);

  const kind = filter === "all" ? undefined : filter;

  const load = React.useCallback(async () => {
    setStatus((prev) => (prev === "ready" ? prev : "loading"));
    setErrorMessage("");
    try {
      const token = (await getToken()) ?? undefined;
      const page = await listUploads({ kind, limit: PAGE_SIZE, offset: 0 }, { token });
      setUploads(page.uploads);
      setHasMore(page.hasMore);
      setNextOffset(page.nextOffset);
      setStatus("ready");
    } catch (err) {
      setErrorMessage(messageOf(err, "Couldn't load your uploads."));
      setStatus("error");
    }
  }, [getToken, kind]);

  React.useEffect(() => {
    if (isLoaded) void load();
  }, [isLoaded, load]);

  const loadMore = React.useCallback(async () => {
    setLoadingMore(true);
    try {
      const token = (await getToken()) ?? undefined;
      const page = await listUploads({ kind, limit: PAGE_SIZE, offset: nextOffset }, { token });
      setUploads((prev) => {
        const seen = new Set(prev.map((u) => u.asset_id));
        return [...prev, ...page.uploads.filter((u) => !seen.has(u.asset_id))];
      });
      setHasMore(page.hasMore && page.uploads.length > 0);
      setNextOffset(page.nextOffset);
    } catch (err) {
      setErrorMessage(messageOf(err, "Couldn't load more uploads."));
    } finally {
      setLoadingMore(false);
    }
  }, [getToken, kind, nextOffset]);

  const onFileChosen = React.useCallback(
    async (event: React.ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      event.target.value = "";
      if (!file) return;
      setUploadError("");
      setUploadProgress(0);
      try {
        const token = (await getToken()) ?? undefined;
        await presignAndUpload(file, {
          token,
          onProgress: (fraction) => setUploadProgress(Math.round(fraction * 100)),
        });
        await load();
      } catch (err) {
        setUploadError(messageOf(err, "Upload failed."));
      } finally {
        setUploadProgress(null);
      }
    },
    [getToken, load],
  );

  const onDelete = React.useCallback(
    async (asset: UploadAsset) => {
      const ok = window.confirm(
        `Delete ${asset.filename || "this upload"}? Reels already made from it are not affected.`,
      );
      if (!ok) return;
      setPendingIds((prev) => new Set(prev).add(asset.asset_id));
      setRowErrors((prev) => {
        const next = { ...prev };
        delete next[asset.asset_id];
        return next;
      });
      try {
        const token = (await getToken()) ?? undefined;
        await deleteUpload(asset.asset_id, { token });
        setUploads((prev) => prev.filter((u) => u.asset_id !== asset.asset_id));
      } catch (err) {
        setRowErrors((prev) => ({
          ...prev,
          [asset.asset_id]: messageOf(err, "Couldn't delete this upload."),
        }));
      } finally {
        setPendingIds((prev) => {
          const next = new Set(prev);
          next.delete(asset.asset_id);
          return next;
        });
      }
    },
    [getToken],
  );

  const uploading = uploadProgress !== null;

  return (
    <main className="min-h-dvh">
      <AppTopBar />
      <section className="container py-8">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
              <FolderUp className="size-6 text-primary" aria-hidden /> Uploads
            </h1>
            <p className="text-sm text-muted-foreground">
              Recordings, voiceovers, photos and clips you uploaded to Menivor.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor="upload-kind" className="sr-only">
              Filter by type
            </label>
            <Select
              id="upload-kind"
              className="w-40"
              value={filter}
              onChange={(e) => setFilter(e.target.value as KindFilter)}
            >
              {FILTERS.map((f) => (
                <option key={f.value} value={f.value}>
                  {f.label}
                </option>
              ))}
            </Select>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void load()}
              disabled={status === "loading"}
            >
              <RefreshCw
                className={status === "loading" ? "size-4 animate-spin" : "size-4"}
                aria-hidden
              />
              Refresh
            </Button>
            <input
              ref={fileInput}
              type="file"
              accept={ACCEPT}
              className="sr-only"
              onChange={(e) => void onFileChosen(e)}
              aria-label="Choose a file to upload"
              tabIndex={-1}
            />
            <Button size="sm" onClick={() => fileInput.current?.click()} disabled={uploading}>
              {uploading ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <Upload className="size-4" aria-hidden />
              )}
              {uploading ? "Uploading" : "Upload file"}
            </Button>
          </div>
        </div>

        {uploading && (
          <div className="mb-4 space-y-1">
            <Progress value={uploadProgress ?? 0} aria-label="Upload progress" />
            <p className="text-xs text-muted-foreground">Uploading your file</p>
          </div>
        )}
        {uploadError && (
          <p className="mb-4 text-sm text-destructive" role="alert">
            {uploadError}
          </p>
        )}

        {status === "loading" && <GridSkeleton />}

        {status === "error" && (
          <Card className="border-destructive/40 bg-destructive/5">
            <CardContent className="flex flex-col items-start gap-3 p-6 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-start gap-3">
                <AlertTriangle className="mt-0.5 size-5 shrink-0 text-destructive" aria-hidden />
                <div>
                  <p className="font-medium">Couldn&apos;t load your uploads</p>
                  <p className="text-sm text-muted-foreground">{errorMessage}</p>
                </div>
              </div>
              <Button variant="outline" size="sm" onClick={() => void load()}>
                <RefreshCw className="size-4" aria-hidden /> Try again
              </Button>
            </CardContent>
          </Card>
        )}

        {status === "ready" && uploads.length === 0 && (
          <Card className="border-dashed">
            <CardContent className="flex flex-col items-center gap-4 py-16 text-center">
              <span className="flex size-12 items-center justify-center rounded-full bg-primary/10">
                <FolderUp className="size-6 text-primary" aria-hidden />
              </span>
              <div>
                <p className="font-medium">
                  {filter === "all" ? "No uploads yet" : "Nothing of this type yet"}
                </p>
                <p className="text-sm text-muted-foreground">
                  Upload a screen recording, voiceover or photo, or add one while creating a reel.
                </p>
              </div>
              <div className="flex flex-wrap justify-center gap-2">
                <Button onClick={() => fileInput.current?.click()} disabled={uploading}>
                  <Upload className="size-4" aria-hidden /> Upload file
                </Button>
                <Button asChild variant="outline">
                  <Link href="/new">Make a product demo</Link>
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {status === "ready" && uploads.length > 0 && (
          <>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {uploads.map((asset) => (
                <UploadTile
                  key={asset.asset_id}
                  asset={asset}
                  pending={pendingIds.has(asset.asset_id)}
                  error={rowErrors[asset.asset_id]}
                  onDelete={() => void onDelete(asset)}
                />
              ))}
            </div>
            {hasMore && (
              <div className="mt-6 flex justify-center">
                <Button variant="outline" onClick={() => void loadMore()} disabled={loadingMore}>
                  {loadingMore && <Loader2 className="size-4 animate-spin" aria-hidden />}
                  Load more
                </Button>
              </div>
            )}
          </>
        )}
      </section>
    </main>
  );
}

function UploadTile({
  asset,
  pending,
  error,
  onDelete,
}: Readonly<{
  asset: UploadAsset;
  pending: boolean;
  error?: string;
  onDelete: () => void;
}>) {
  const Icon = KIND_ICON[asset.kind];
  const url = asset.get_url;
  const meta = [formatBytes(asset.size), formatDate(asset.created_at)].filter(Boolean).join(" · ");

  return (
    <Card className="overflow-hidden">
      <div className="flex aspect-video items-center justify-center overflow-hidden border-b border-border bg-muted">
        {url && asset.kind === "image" ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={url} alt={asset.filename ?? "Uploaded image"} className="h-full w-full object-cover" loading="lazy" />
        ) : url && asset.kind === "video" ? (
          <video src={url} controls playsInline preload="metadata" className="h-full w-full bg-black object-contain" />
        ) : url && asset.kind === "audio" ? (
          <div className="flex w-full flex-col items-center gap-3 px-3">
            <Icon className="size-8 text-muted-foreground" aria-hidden />
            <audio src={url} controls preload="none" className="w-full" />
          </div>
        ) : (
          <Icon className="size-8 text-muted-foreground" aria-hidden />
        )}
      </div>
      <CardContent className="space-y-2 p-4">
        <div className="flex items-start justify-between gap-2">
          <p className="min-w-0 truncate text-sm font-medium" title={asset.filename}>
            {asset.filename || asset.key}
          </p>
          <Badge variant="outline" className="shrink-0 capitalize">
            {asset.kind === "upload" ? "file" : asset.kind}
          </Badge>
        </div>
        {meta && <p className="text-xs text-muted-foreground">{meta}</p>}
        <div className="flex items-center justify-between gap-2">
          {url ? (
            <Button asChild variant="outline" size="sm">
              <a
                href={asset.download_url ?? url}
                download
                target="_blank"
                rel="noopener noreferrer"
              >
                <Download className="size-4" aria-hidden /> Download
              </a>
            </Button>
          ) : (
            <span className="text-xs text-muted-foreground">Preview unavailable</span>
          )}
          <Button
            variant="ghost"
            size="sm"
            className="text-muted-foreground hover:text-destructive"
            onClick={onDelete}
            disabled={pending}
            aria-label={`Delete ${asset.filename || "upload"}`}
          >
            {pending ? (
              <Loader2 className="size-4 animate-spin" aria-hidden />
            ) : (
              <Trash2 className="size-4" aria-hidden />
            )}
            Delete
          </Button>
        </div>
        {error && (
          <p className="text-xs text-destructive" role="alert">
            {error}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function GridSkeleton() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {Array.from({ length: 8 }).map((_, i) => (
        <Card key={i} className="overflow-hidden">
          <Skeleton className="aspect-video w-full rounded-none" />
          <CardContent className="space-y-2 p-4">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-3 w-1/2" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
