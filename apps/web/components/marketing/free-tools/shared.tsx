"use client";

import { useState } from "react";
import Link from "next/link";
import { AlertTriangle, Check, Copy, Download } from "lucide-react";
import { Button } from "@/components/ui/button";

/** Trigger a client-side download of text or a blob. */
export function downloadBlob(data: Blob | string, filename: string, type = "text/plain"): void {
  const blob = typeof data === "string" ? new Blob([data], { type: `${type};charset=utf-8` }) : data;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/**
 * Legacy fallback for environments where the async Clipboard API is missing
 * or denied (`document.execCommand` is deprecated but still the only copy
 * path in several in-app browsers and locked-down iframes).
 */
function legacyCopy(text: string): boolean {
  if (typeof document === "undefined") return false;
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  area.style.pointerEvents = "none";
  document.body.appendChild(area);
  area.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }
  area.remove();
  return ok;
}

/**
 * Copy `text` to the clipboard, falling back to the legacy `execCommand`
 * path when `navigator.clipboard.writeText` is missing or throws (clipboard
 * permissions are commonly denied inside webviews/iframes — including the
 * TikTok and Instagram in-app browsers that are a realistic source of
 * traffic on these free tool pages). Returns whether the copy succeeded, so
 * callers can surface a real failure instead of assuming success.
 */
export async function copyText(text: string): Promise<boolean> {
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Clipboard API present but denied/unsupported here; fall through.
    }
  }
  return legacyCopy(text);
}

interface CopyButtonProps {
  readonly text: string;
  readonly label?: string;
  readonly size?: "sm" | "md";
}

type CopyStatus = "idle" | "copied" | "failed";

export function CopyButton({ text, label = "Copy", size = "sm" }: CopyButtonProps) {
  const [status, setStatus] = useState<CopyStatus>("idle");
  return (
    <Button
      type="button"
      variant="outline"
      size={size}
      disabled={!text}
      onClick={async () => {
        const ok = await copyText(text);
        setStatus(ok ? "copied" : "failed");
        setTimeout(() => setStatus("idle"), 1500);
      }}
    >
      {status === "copied" ? (
        <Check className="size-4" />
      ) : status === "failed" ? (
        <AlertTriangle className="size-4" />
      ) : (
        <Copy className="size-4" />
      )}
      <span aria-live="polite">
        {status === "copied" ? "Copied" : status === "failed" ? "Couldn't copy" : label}
      </span>
    </Button>
  );
}

interface DownloadButtonProps {
  readonly text: string;
  readonly filename: string;
  readonly label: string;
  readonly type?: string;
}

export function DownloadButton({ text, filename, label, type }: DownloadButtonProps) {
  return (
    <Button type="button" variant="outline" size="sm" disabled={!text} onClick={() => downloadBlob(text, filename, type)}>
      <Download className="size-4" />
      {label}
    </Button>
  );
}

/** Frame around every interactive widget. */
export function ToolPanel({ children }: { readonly children: React.ReactNode }) {
  return (
    <section
      aria-label="Tool"
      className="mt-8 rounded-xl border border-border bg-card p-5 shadow-sm sm:p-6"
    >
      {children}
    </section>
  );
}

/** Soft upsell shown after a successful result. Never blocks the result. */
export function SoftCta({ text }: { readonly text: string }) {
  return (
    <p className="mt-5 rounded-md border border-primary/30 bg-primary/5 px-4 py-3 text-sm text-muted-foreground">
      {text}{" "}
      <Link href="/sign-up" className="font-semibold text-primary underline-offset-4 hover:underline">
        Make it a finished video free
      </Link>
    </p>
  );
}

export function ErrorNote({ message }: { readonly message: string }) {
  return (
    <p role="alert" className="mt-4 rounded-md border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
      {message}
    </p>
  );
}

export const fieldLabel = "mb-1.5 block text-sm font-medium text-foreground";

/** Read a user-picked text file, refusing anything over `maxBytes`. */
export async function readTextFile(file: File, maxBytes = 5_000_000): Promise<string> {
  if (file.size > maxBytes) throw new Error("That file is too large (5 MB max).");
  return file.text();
}
