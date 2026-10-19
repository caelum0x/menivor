import Link from "next/link";
import { Sparkles, Trophy } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { RankedStyle, Winner } from "./api";
import { presetLabel, remakeHref, shortCount } from "./view-model";

/** The one thing to know (which hook wins) and the one thing to do next. */
export function WinnerCard({
  winner,
  styles,
}: Readonly<{ winner: Winner; styles: readonly RankedStyle[] }>) {
  const style = presetLabel(winner.remake.preset);
  const topStyle = styles.length > 1 ? styles[0] : null;
  return (
    <section className="glass-strong rounded-3xl p-6 sm:p-8">
      <p className="flex items-center gap-2 text-sm font-medium text-primary">
        <Trophy className="size-4" aria-hidden />
        Your best hook
      </p>
      <blockquote className="mt-3 text-2xl font-semibold leading-snug tracking-tight sm:text-3xl">
        &ldquo;{winner.hook}&rdquo;
      </blockquote>
      <p className="mt-3 text-muted-foreground">
        {winner.why}
        {style ? ` Style: ${style}.` : ""}
      </p>
      <div className="mt-6 flex flex-wrap items-center gap-4">
        <Button asChild size="lg" className="neu-primary">
          <Link href={remakeHref(winner.remake)}>
            <Sparkles className="size-4" aria-hidden />
            Make more like this
          </Link>
        </Button>
        {topStyle && presetLabel(topStyle.preset) && topStyle.avg_views !== null ? (
          <p className="text-sm text-muted-foreground">
            Best style: <span className="font-medium text-foreground">{presetLabel(topStyle.preset)}</span>
            {" "}({shortCount(topStyle.avg_views)} views per post)
          </p>
        ) : null}
      </div>
    </section>
  );
}
