import type { SeriesPoint } from "./api";
import { chartGeometry, shortCount, shortDate } from "./view-model";

const WIDTH = 600;
const HEIGHT = 140;

/** Total views across all tracked posts, one point per day. */
export function ViewsChart({ series }: Readonly<{ series: readonly SeriesPoint[] }>) {
  const geo = chartGeometry(series, WIDTH, HEIGHT);
  if (!geo) return null;
  const label = `Views grew from ${shortCount(geo.first.views) || "0"} on ${shortDate(geo.first.date)} to ${
    shortCount(geo.last.views) || "0"
  } on ${shortDate(geo.last.date)}.`;
  return (
    <section className="glass rounded-2xl p-5">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-medium text-muted-foreground">Views across your posts</h2>
        <p className="text-2xl font-semibold tabular-nums">{shortCount(geo.last.views) || "0"}</p>
      </div>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        preserveAspectRatio="none"
        className="h-36 w-full text-primary"
        role="img"
        aria-label={label}
      >
        <defs>
          <linearGradient id="results-area" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="currentColor" stopOpacity="0.25" />
            <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={geo.area} fill="url(#results-area)" />
        <path
          d={geo.line}
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <div className="mt-2 flex justify-between text-xs text-muted-foreground">
        <span>{shortDate(geo.first.date)}</span>
        <span>{shortDate(geo.last.date)}</span>
      </div>
    </section>
  );
}
