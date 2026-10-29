"use client";

/**
 * "Share to X" for a finished reel. Opens X's web intent in a new tab.
 * X cannot attach the MP4, so when a download URL is present the click
 * starts that download first, then the composer opens.
 */

import * as React from "react";
import { Button } from "@/components/ui/button";
import type { ButtonSize, ButtonVariant } from "@/components/ui/button";
import { useTranslations } from "@/lib/i18n/context";
import { cn } from "@/lib/utils";
import { buildXIntent, normalizeHttpUrl, type XShareInput } from "./x-intent";

const DOWNLOAD_FRAME = "menivor-share-x-download";

export interface ShareToXProps extends XShareInput {
  /** Finished MP4. When set, the click downloads it before the composer opens. */
  readonly downloadUrl?: string | null;
  readonly downloadFilename?: string;
  readonly variant?: ButtonVariant;
  readonly size?: ButtonSize;
  readonly className?: string;
}

/** Download into a hidden frame so the current page stays put. */
export function startMp4Download(url: string, filename: string): void {
  if (typeof document === "undefined") return;
  let frame = document.querySelector<HTMLIFrameElement>(`iframe[name="${DOWNLOAD_FRAME}"]`);
  if (!frame) {
    frame = document.createElement("iframe");
    frame.name = DOWNLOAD_FRAME;
    frame.hidden = true;
    frame.setAttribute("aria-hidden", "true");
    document.body.appendChild(frame);
  }
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.target = DOWNLOAD_FRAME;
  anchor.rel = "noopener noreferrer";
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}

function safeFilename(name: string | undefined): string {
  const cleaned = (name ?? "").replace(/[\\/\u0000"]/g, "").trim();
  return cleaned || "reel.mp4";
}

function XLogo() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className="size-4" fill="currentColor">
      <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.744l7.727-8.835L1.254 2.25H8.08l4.253 5.622L18.244 2.25zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
    </svg>
  );
}

export function ShareToX({
  hook,
  hooks,
  hashtags,
  sourceUrl,
  downloadUrl,
  downloadFilename,
  variant = "outline",
  size = "sm",
  className,
}: Readonly<ShareToXProps>) {
  const t = useTranslations();
  const hintId = React.useId();
  const intent = buildXIntent({ hook, hooks, hashtags, sourceUrl });
  const fileUrl = normalizeHttpUrl(downloadUrl);
  const label = t("shareToX.button");
  const ariaLabel = fileUrl ? t("shareToX.downloadAndShareAria") : t("shareToX.buttonAria");

  return (
    <div className={cn("flex max-w-xs flex-col items-start gap-1", className)}>
      <Button asChild variant={variant} size={size}>
        <a
          href={intent.href}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={ariaLabel}
          aria-describedby={hintId}
          onClick={() => {
            if (fileUrl) startMp4Download(fileUrl, safeFilename(downloadFilename));
          }}
        >
          <XLogo />
          {label}
        </a>
      </Button>
      <p id={hintId} className="text-xs leading-snug text-muted-foreground">
        {t("shareToX.hint")}
      </p>
    </div>
  );
}
