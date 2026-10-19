"use client";

import * as React from "react";
import { Check, Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface CopyBoxProps {
  /** The text shown in the box and copied to the clipboard. */
  value: string;
  /** Accessible label for the copy button (e.g. "Copy API key"). */
  label: string;
  /** Render the value with a monospace secret style (default true). */
  mono?: boolean;
  className?: string;
}

/**
 * A read-only value in a bordered box with a copy-to-clipboard button. Shows a
 * transient "Copied" confirmation. Degrades gracefully when the Clipboard API is
 * unavailable (e.g. non-secure context) — the value is always selectable.
 */
export function CopyBox({ value, label, mono = true, className }: CopyBoxProps) {
  const [copied, setCopied] = React.useState(false);
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  React.useEffect(() => {
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  const handleCopy = React.useCallback(async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard unavailable — the value stays selectable for a manual copy.
      setCopied(false);
    }
  }, [value]);

  return (
    <div
      className={cn(
        "flex items-stretch gap-2 rounded-lg border border-border bg-secondary/30 p-2",
        className,
      )}
    >
      <code
        className={cn(
          "min-w-0 flex-1 overflow-x-auto whitespace-pre px-2 py-1.5 text-sm",
          mono ? "font-mono" : "",
        )}
      >
        {value}
      </code>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={handleCopy}
        aria-label={label}
        className="shrink-0 self-center"
      >
        {copied ? (
          <>
            <Check className="size-4" aria-hidden /> Copied
          </>
        ) : (
          <>
            <Copy className="size-4" aria-hidden /> Copy
          </>
        )}
      </Button>
    </div>
  );
}
