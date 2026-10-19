import { CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { LaunchFormat } from "../_lib/launch";

/** Plain-language description per keyless format (server label stays the title). */
const FORMAT_DETAIL: Record<string, string> = {
  captions_only_byov:
    "Upload a video you recorded. Its own audio is transcribed and word-by-word captions are burned in. No AI provider is called.",
  faceless_tts_free_voice:
    "Type your script, pick a free neural voice and a background loop. You get a narrated, captioned 9:16 reel.",
};

export interface AvailableFormatsProps {
  readonly formats: readonly LaunchFormat[];
  readonly className?: string;
}

/**
 * The formats a private-beta user can make today, straight from the server's
 * readiness payload. When the server reports none ready, say so plainly
 * instead of listing formats that would fail.
 */
export function AvailableFormats({ formats, className }: AvailableFormatsProps) {
  if (formats.length === 0) {
    return (
      <p className={cn("text-sm text-muted-foreground", className)}>
        No format is rendering on the beta servers yet. Approved requests get an email
        once one is live.
      </p>
    );
  }
  return (
    <div className={cn("space-y-3", className)}>
      <p className="text-sm font-medium text-foreground">Available in the beta now</p>
      <ul className="space-y-3">
        {formats.map((format) => (
          <li key={format.id} className="flex gap-3">
            <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
            <div>
              <p className="text-sm font-medium text-foreground">{format.label}</p>
              <p className="text-sm text-muted-foreground">
                {FORMAT_DETAIL[format.id] ?? format.notes}
              </p>
            </div>
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted-foreground">
        Both are free during the beta.
      </p>
    </div>
  );
}
