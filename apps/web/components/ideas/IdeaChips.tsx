import { Clock, Film, Languages, Layout as LayoutIcon } from "lucide-react";
import type { Idea } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import {
  captionStyleMeta,
  languageLabel,
  layoutLabel,
} from "@/components/ideas/idea-mapping";

interface IdeaChipsProps {
  idea: Readonly<Idea>;
}

/**
 * The suggestion chips row shared by generated and saved idea cards: layout,
 * caption style (with a two-tone swatch), language, format, and duration.
 */
export function IdeaChips({ idea }: IdeaChipsProps) {
  const caption = captionStyleMeta(idea.suggested_caption_style);

  return (
    <div className="flex flex-wrap gap-1.5">
      <Badge variant="secondary">
        <LayoutIcon className="size-3" aria-hidden />
        {layoutLabel(idea.suggested_layout)}
      </Badge>

      <Badge variant="secondary">
        <span
          className="size-3 rounded-full border border-border/60"
          aria-hidden
          style={{
            background: `linear-gradient(90deg, ${caption.spoken} 50%, ${caption.upcoming} 50%)`,
          }}
        />
        {caption.label}
      </Badge>

      <Badge variant="secondary">
        <Languages className="size-3" aria-hidden />
        {languageLabel(idea.language)}
      </Badge>

      {idea.format && (
        <Badge variant="outline">
          <Film className="size-3" aria-hidden />
          {idea.format}
        </Badge>
      )}

      <Badge variant="outline">
        <Clock className="size-3" aria-hidden />
        {idea.est_duration_s}s
      </Badge>
    </div>
  );
}
