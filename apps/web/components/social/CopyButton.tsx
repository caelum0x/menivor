"use client";

import * as React from "react";
import { Check, Copy } from "lucide-react";
import { Button, type ButtonProps } from "@/components/ui/button";

export interface CopyButtonProps {
  /** Text written to the clipboard when pressed. */
  value: string;
  /** Accessible label describing what is copied (e.g. "Copy caption"). */
  label: string;
  className?: string;
  variant?: ButtonProps["variant"];
  size?: ButtonProps["size"];
  /** Optional visible content shown next to the icon (e.g. a chip's text). */
  children?: React.ReactNode;
}

/**
 * Small copy-to-clipboard button with transient "copied" / "failed" feedback.
 * Reused for the title, caption, each hashtag chip, and the "copy all" action.
 * The clipboard write is guarded — an unavailable/denied Clipboard API surfaces a
 * brief hint instead of throwing.
 */
export function CopyButton({
  value,
  label,
  className,
  variant = "outline",
  size = "sm",
  children,
}: Readonly<CopyButtonProps>) {
  const [state, setState] = React.useState<"idle" | "copied" | "failed">("idle");
  const timerRef = React.useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );

  React.useEffect(
    () => () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    },
    [],
  );

  const flash = React.useCallback((next: "copied" | "failed") => {
    setState(next);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(
      () => setState("idle"),
      next === "copied" ? 1500 : 2500,
    );
  }, []);

  const handleCopy = React.useCallback(async () => {
    try {
      if (!navigator.clipboard?.writeText) {
        throw new Error("Clipboard API unavailable");
      }
      await navigator.clipboard.writeText(value);
      flash("copied");
    } catch {
      flash("failed");
    }
  }, [value, flash]);

  const title =
    state === "failed" ? "Couldn't copy — select and copy manually." : label;

  return (
    <Button
      type="button"
      variant={variant}
      size={size}
      className={className}
      disabled={value.length === 0}
      aria-label={label}
      title={title}
      onClick={() => void handleCopy()}
    >
      {state === "copied" ? (
        <Check className="size-4" aria-hidden />
      ) : (
        <Copy className="size-4" aria-hidden />
      )}
      {children}
      <span className="sr-only" aria-live="polite">
        {state === "copied"
          ? "Copied to clipboard"
          : state === "failed"
            ? "Copy failed"
            : ""}
      </span>
    </Button>
  );
}
