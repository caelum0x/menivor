"use client";

import * as React from "react";
import { Share2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ButtonSize, ButtonVariant } from "@/components/ui/button";
import { ShareDialog } from "@/components/share/ShareDialog";

export interface ShareButtonProps {
  /** The caller's OWN finished reel to share (passed to {@link ShareDialog}). */
  jobId: string;
  /** Idle button label. Defaults to "Share". */
  label?: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
  className?: string;
}

/**
 * Reel-level affordance that opens the {@link ShareDialog} to mint + copy a
 * PUBLIC share link for the caller's OWN reel. Drop it onto a JobCard / reel
 * detail view. The dialog state is local so multiple ShareButtons on a list each
 * manage their own reel independently.
 */
export function ShareButton({
  jobId,
  label = "Share",
  variant = "outline",
  size = "sm",
  className,
}: Readonly<ShareButtonProps>) {
  const [open, setOpen] = React.useState(false);

  return (
    <>
      <Button
        type="button"
        variant={variant}
        size={size}
        className={className}
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
        aria-label={`Share reel`}
      >
        <Share2 className="size-4" aria-hidden />
        {label}
      </Button>
      <ShareDialog jobId={jobId} open={open} onClose={() => setOpen(false)} />
    </>
  );
}
