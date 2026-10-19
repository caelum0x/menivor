"use client";

import * as React from "react";
import {
  Archive,
  ArchiveRestore,
  Ban,
  Check,
  Loader2,
  Pencil,
  Trash2,
  X,
} from "lucide-react";
import { isTerminalState, type Job } from "@/lib/types";
import { jobDisplayTitle } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { ReelActionHandlers } from "../use-reel-actions";

const TITLE_MAX = 120;

export interface ReelActionsProps {
  job: Job;
  actions: ReelActionHandlers;
  /** Show text labels next to the icons (detail page) instead of icon-only. */
  labelled?: boolean;
  /** Called after a successful delete (e.g. navigate back to the library). */
  onDeleted?: () => void;
  /** Horizontal alignment of the control row (default: end). */
  align?: "start" | "end";
  className?: string;
}

/**
 * Rename / archive / cancel / delete controls for one reel. Cancel is offered
 * only while the reel is still rendering (unspent credits are refunded);
 * delete only once it is finished, so a running job is never orphaned.
 */
export function ReelActions({
  job,
  actions,
  labelled = false,
  onDeleted,
  align = "end",
  className,
}: Readonly<ReelActionsProps>) {
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState("");
  const pending = actions.pendingIds.has(job.job_id);
  const error = actions.errors[job.job_id];
  const terminal = isTerminalState(job.state);
  const size = labelled ? "sm" : "icon";
  const compact = labelled ? undefined : "h-8 w-8";

  const startRename = () => {
    setDraft(job.title?.trim() || "");
    setEditing(true);
  };

  const submitRename = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const ok = await actions.rename(job, draft.slice(0, TITLE_MAX));
    if (ok) setEditing(false);
  };

  const confirmCancel = async () => {
    const ok = window.confirm(
      "Cancel this reel? Rendering stops and any unspent credits go back to your balance.",
    );
    if (ok) await actions.cancel(job);
  };

  const confirmDelete = async () => {
    const ok = window.confirm(
      `Delete "${jobDisplayTitle(job)}"? This removes it from your library and cannot be undone.`,
    );
    if (!ok) return;
    const deleted = await actions.remove(job);
    if (deleted) onDeleted?.();
  };

  if (editing) {
    return (
      <form
        onSubmit={(e) => void submitRename(e)}
        className={`flex items-center gap-1.5 ${className ?? ""}`}
      >
        <label htmlFor={`rename-${job.job_id}`} className="sr-only">
          Reel title
        </label>
        <Input
          id={`rename-${job.job_id}`}
          value={draft}
          maxLength={TITLE_MAX}
          placeholder={jobDisplayTitle(job)}
          onChange={(e) => setDraft(e.target.value)}
          className="h-8 w-44"
          autoFocus
          disabled={pending}
        />
        <Button type="submit" size="icon" variant="ghost" className="h-8 w-8" disabled={pending} aria-label="Save title">
          {pending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Check className="size-4" aria-hidden />}
        </Button>
        <Button
          type="button"
          size="icon"
          variant="ghost"
          className="h-8 w-8"
          onClick={() => setEditing(false)}
          disabled={pending}
          aria-label="Cancel rename"
        >
          <X className="size-4" aria-hidden />
        </Button>
        {error && <span className="text-xs text-destructive" role="alert">{error}</span>}
      </form>
    );
  }

  return (
    <div
      className={`flex flex-col gap-1 ${align === "start" ? "items-start" : "items-end"} ${className ?? ""}`}
    >
      <div
        className={`flex flex-wrap items-center gap-1 ${align === "start" ? "justify-start" : "justify-end"}`}
      >
        {pending && <Loader2 className="size-4 animate-spin text-muted-foreground" aria-label="Working" />}
        <Button
          type="button"
          size={size}
          variant="ghost"
          className={compact}
          onClick={startRename}
          disabled={pending}
          aria-label="Rename reel"
          title="Rename"
        >
          <Pencil className="size-4" aria-hidden />
          {labelled && "Rename"}
        </Button>
        {!terminal && (
          <Button
            type="button"
            size={size}
            variant="ghost"
            className={compact}
            onClick={() => void confirmCancel()}
            disabled={pending}
            aria-label="Cancel reel and refund credits"
            title="Cancel and refund"
          >
            <Ban className="size-4" aria-hidden />
            {labelled && "Cancel render"}
          </Button>
        )}
        <Button
          type="button"
          size={size}
          variant="ghost"
          className={compact}
          onClick={() => void actions.setArchived(job, !job.archived)}
          disabled={pending}
          aria-label={job.archived ? "Restore reel from archive" : "Archive reel"}
          title={job.archived ? "Restore" : "Archive"}
        >
          {job.archived ? (
            <ArchiveRestore className="size-4" aria-hidden />
          ) : (
            <Archive className="size-4" aria-hidden />
          )}
          {labelled && (job.archived ? "Restore" : "Archive")}
        </Button>
        {terminal && (
          <Button
            type="button"
            size={size}
            variant="ghost"
            className={`text-muted-foreground hover:text-destructive ${compact ?? ""}`}
            onClick={() => void confirmDelete()}
            disabled={pending}
            aria-label="Delete reel"
            title="Delete"
          >
            <Trash2 className="size-4" aria-hidden />
            {labelled && "Delete"}
          </Button>
        )}
      </div>
      {error && (
        <p
          className={`max-w-[18rem] text-xs text-destructive ${align === "start" ? "text-left" : "text-right"}`}
          role="alert"
        >
          {error}
        </p>
      )}
    </div>
  );
}
