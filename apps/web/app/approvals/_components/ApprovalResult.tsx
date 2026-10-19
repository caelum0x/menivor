"use client";

import Link from "next/link";

/**
 * What approving an item actually did, from `item.result` (written by the source
 * adapter in apps/api/app/domains/approvals/producers.py and adapters.py):
 * queued posts, platforms skipped with their reason, reel jobs, Ad Studio renders.
 */

interface ResultPost {
  id: string;
  platform: string;
  status: string;
  scheduled_at: string | null;
  channel_label?: string;
}

interface SkippedPlatform {
  platform: string;
  message: string;
}

function asRecords<T>(value: unknown, isValid: (row: Record<string, unknown>) => boolean): T[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (row): row is Record<string, unknown> => typeof row === "object" && row !== null && isValid(row as Record<string, unknown>),
  ) as unknown as T[];
}

function asStrings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string" && v.length > 0) : [];
}

function when(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
}

export function ApprovalResult({ result }: { result: Record<string, unknown> }) {
  const posts = asRecords<ResultPost>(result.posts, (r) => typeof r.id === "string" && typeof r.platform === "string");
  const skipped = asRecords<SkippedPlatform>(result.skipped, (r) => typeof r.platform === "string");
  const jobIds = asStrings(result.job_ids);
  const variantIds = asStrings(result.variant_ids);
  const enqueueFailures = asStrings(result.enqueue_failures);
  const projectId = typeof result.project_id === "string" ? result.project_id : "";
  const credits = typeof result.credits === "number" ? result.credits : null;
  const note = typeof result.note === "string" ? result.note : "";
  const replayed = result.replayed === true;

  if (!posts.length && !skipped.length && !jobIds.length && !projectId && !note) return null;

  return (
    <div className="space-y-2 rounded-md border bg-muted/30 p-3 text-sm">
      {posts.length ? (
        <div>
          <p className="text-xs font-medium text-muted-foreground">Queued posts</p>
          <ul className="mt-1 space-y-0.5">
            {posts.map((post) => (
              <li key={post.id} className="flex flex-wrap items-center gap-x-2">
                <span className="font-medium capitalize">{post.platform.replace(/_/g, " ")}</span>
                {post.channel_label ? <span className="text-muted-foreground">{post.channel_label}</span> : null}
                <span className="text-muted-foreground">
                  {post.status}
                  {post.scheduled_at ? `, ${when(post.scheduled_at)}` : ""}
                </span>
              </li>
            ))}
          </ul>
          <Link href="/publish" className="mt-1 inline-block text-xs underline underline-offset-4">
            Open the publish queue
          </Link>
        </div>
      ) : null}

      {skipped.length ? (
        <div>
          <p className="text-xs font-medium text-muted-foreground">Not posted</p>
          <ul className="mt-1 space-y-0.5">
            {skipped.map((row, i) => (
              <li key={`${row.platform}-${i}`}>
                <span className="font-medium capitalize">{row.platform.replace(/_/g, " ")}</span>
                {row.message ? <span className="text-muted-foreground">: {row.message}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {jobIds.length ? (
        <div>
          <p className="text-xs font-medium text-muted-foreground">
            Reel jobs{credits !== null && !replayed ? ` (${credits} credit${credits === 1 ? "" : "s"})` : ""}
            {replayed ? " (already created earlier; not charged again)" : ""}
          </p>
          <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
            {jobIds.map((id) => (
              <li key={id}>
                <Link href={`/jobs/${encodeURIComponent(id)}`} className="font-mono text-xs underline underline-offset-4">
                  {id}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {enqueueFailures.length ? (
        <p className="text-xs text-destructive">
          {enqueueFailures.length} job(s) could not be started; their credits were refunded.
        </p>
      ) : null}

      {projectId ? (
        <p>
          <Link href={`/ad-studio/${encodeURIComponent(projectId)}`} className="underline underline-offset-4">
            Open the Ad Studio project
          </Link>
          <span className="text-muted-foreground">
            {variantIds.length ? `, ${variantIds.length} ad(s) rendering` : ""}
          </span>
        </p>
      ) : null}

      {note ? <p className="text-xs text-muted-foreground">{note}</p> : null}
    </div>
  );
}
