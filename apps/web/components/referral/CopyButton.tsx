"use client";

import * as React from "react";
import { Check, Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ButtonSize, ButtonVariant } from "@/components/ui/button";

interface CopyButtonProps {
  /** The text written to the clipboard when pressed. */
  readonly value: string;
  /** Idle button label. Defaults to "Copy". */
  readonly label?: string;
  readonly variant?: ButtonVariant;
  readonly size?: ButtonSize;
  readonly className?: string;
}

/**
 * Copies `value` to the clipboard and shows a transient "Copied" confirmation.
 * Degrades gracefully when the Clipboard API is unavailable (e.g. an insecure
 * context) — the underlying value stays visible for manual selection.
 */
export function CopyButton({
  value,
  label = "Copy",
  variant = "outline",
  size = "sm",
  className,
}: CopyButtonProps) {
  const [copied, setCopied] = React.useState(false);
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  React.useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const onCopy = React.useCallback(async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard unavailable — no-op; value remains visible to copy manually.
    }
  }, [value]);

  return (
    <Button
      type="button"
      variant={variant}
      size={size}
      onClick={() => void onCopy()}
      className={className}
      aria-label={copied ? "Copied to clipboard" : label}
    >
      {copied ? (
        <Check className="size-4 text-success" aria-hidden />
      ) : (
        <Copy className="size-4" aria-hidden />
      )}
      {copied ? "Copied" : label}
    </Button>
  );
}
