"use client";

import * as React from "react";
import { AlertCircle, Loader2, Upload, X } from "lucide-react";
import type { Layout, PublishTemplateRequest } from "@/lib/types";
import { ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { DUB_LANGUAGE_CODES } from "@/lib/types";
import { languageLabel } from "@/components/marketplace/format";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export interface PublishDialogProps {
  open: boolean;
  onClose: () => void;
  /** Publishes the inline snapshot; resolves when the listing is created. */
  onPublish: (body: PublishTemplateRequest) => Promise<unknown>;
}

type SubmitState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "error"; message: string };

const LAYOUT_OPTIONS: readonly { value: Layout; label: string }[] = [
  { value: "pip", label: "Picture-in-picture" },
  { value: "hook_intro", label: "Hook intro" },
  { value: "split", label: "Split screen" },
];

/** Split a comma/newline separated tag string into a deduped, trimmed list. */
function parseTags(raw: string): string[] {
  const seen = new Set<string>();
  for (const part of raw.split(/[,\n]/)) {
    const tag = part.trim();
    if (tag) seen.add(tag);
  }
  return Array.from(seen);
}

/**
 * A modal form to publish a NEW template snapshot inline to the public
 * marketplace. Title is required (empty is blocked client-side before the
 * request). The published listing is an immutable copy — the backend snapshots
 * these fields at publish time. Closes on Escape, backdrop click, or success.
 */
export function PublishDialog({
  open,
  onClose,
  onPublish,
}: Readonly<PublishDialogProps>) {
  const [title, setTitle] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [prompt, setPrompt] = React.useState("");
  const [tags, setTags] = React.useState("");
  const [language, setLanguage] = React.useState<string>("en");
  const [layout, setLayout] = React.useState<Layout>("pip");
  const [submit, setSubmit] = React.useState<SubmitState>({ status: "idle" });

  const reset = React.useCallback(() => {
    setTitle("");
    setDescription("");
    setPrompt("");
    setTags("");
    setLanguage("en");
    setLayout("pip");
    setSubmit({ status: "idle" });
  }, []);

  const handleClose = React.useCallback(() => {
    if (submit.status === "submitting") return;
    reset();
    onClose();
  }, [onClose, reset, submit.status]);

  React.useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") handleClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, handleClose]);

  const handleSubmit = React.useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault();
      const trimmedTitle = title.trim();
      if (!trimmedTitle) {
        setSubmit({ status: "error", message: "A title is required." });
        return;
      }
      setSubmit({ status: "submitting" });
      try {
        await onPublish({
          title: trimmedTitle,
          description: description.trim(),
          prompt: prompt.trim(),
          tags: parseTags(tags),
          language,
          layout,
        });
        reset();
      } catch (err) {
        const message =
          friendlyErrorMessage(err, "Couldn't publish this template.");
        setSubmit({ status: "error", message });
      }
    },
    [description, language, layout, onPublish, prompt, reset, tags, title],
  );

  if (!open) return null;

  const submitting = submit.status === "submitting";

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-background/80 p-4 backdrop-blur-sm sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="publish-dialog-title"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) handleClose();
      }}
    >
      <div className="w-full max-w-lg rounded-lg border border-border bg-card shadow-lg">
        <div className="flex items-start justify-between gap-3 border-b border-border p-5">
          <div>
            <h2
              id="publish-dialog-title"
              className="text-lg font-semibold leading-none tracking-tight"
            >
              Publish a template
            </h2>
            <p className="mt-1.5 text-sm text-muted-foreground">
              Share a reusable template with the community. Published listings are
              an immutable snapshot.
            </p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Close"
            onClick={handleClose}
            disabled={submitting}
          >
            <X className="size-4" aria-hidden />
          </Button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 p-5">
          <div className="space-y-1.5">
            <Label htmlFor="publish-title">Title</Label>
            <Input
              id="publish-title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="e.g. 3 apps that make you look productive"
              maxLength={300}
              required
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="publish-description">Description</Label>
            <Textarea
              id="publish-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="What this template is great for."
              rows={2}
              maxLength={4000}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="publish-prompt">Prompt / scaffold</Label>
            <Textarea
              id="publish-prompt"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder="The prompt scaffold used to seed the reel."
              rows={3}
              maxLength={8000}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="publish-tags">Tags</Label>
            <Input
              id="publish-tags"
              value={tags}
              onChange={(event) => setTags(event.target.value)}
              placeholder="Comma separated, e.g. listicle, saas"
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="publish-language">Language</Label>
              <Select
                id="publish-language"
                value={language}
                onChange={(event) => setLanguage(event.target.value)}
              >
                {DUB_LANGUAGE_CODES.map((code) => (
                  <option key={code} value={code}>
                    {languageLabel(code)}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="publish-layout">Layout</Label>
              <Select
                id="publish-layout"
                value={layout}
                onChange={(event) => setLayout(event.target.value as Layout)}
              >
                {LAYOUT_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          {submit.status === "error" && (
            <p
              role="alert"
              className="flex items-center gap-1.5 text-sm text-destructive"
            >
              <AlertCircle className="size-4 shrink-0" aria-hidden />
              {submit.message}
            </p>
          )}

          <div className="flex items-center justify-end gap-2 pt-1">
            <Button
              type="button"
              variant="outline"
              onClick={handleClose}
              disabled={submitting}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={submitting || title.trim() === ""}>
              {submitting ? (
                <>
                  <Loader2 className="animate-spin" aria-hidden /> Publishing…
                </>
              ) : (
                <>
                  <Upload aria-hidden /> Publish
                </>
              )}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
