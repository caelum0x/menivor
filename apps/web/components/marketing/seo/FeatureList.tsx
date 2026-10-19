import { Check } from "lucide-react";

/**
 * A simple check-marked bullet list used for feature highlights and
 * "menivor edge" points. Presentational only.
 */
interface FeatureListProps {
  readonly items: readonly string[];
  readonly className?: string;
}

export function FeatureList({ items, className }: FeatureListProps) {
  return (
    <ul className={className ? `space-y-2.5 ${className}` : "space-y-2.5"}>
      {items.map((item) => (
        <li key={item} className="flex items-start gap-2.5">
          <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary">
            <Check className="size-3.5" />
          </span>
          <span className="text-pretty text-muted-foreground">{item}</span>
        </li>
      ))}
    </ul>
  );
}
