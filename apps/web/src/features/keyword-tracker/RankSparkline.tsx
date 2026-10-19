import type { HistoryPoint } from "./api";
import { rankChartGeometry } from "./view-model";

const WIDTH = 120;
const HEIGHT = 32;

/** A tiny inline rank-history chart for one row of the keywords table. */
export function RankSparkline({ history }: Readonly<{ history: readonly HistoryPoint[] }>) {
  const geo = rankChartGeometry(history, WIDTH, HEIGHT);
  if (!geo) {
    return <span className="text-xs text-muted-foreground">Not enough history yet</span>;
  }
  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      preserveAspectRatio="none"
      className="h-8 w-[120px] text-primary"
      role="img"
      aria-label={`Rank history, best (lowest) rank seen was better than #${geo.worst}`}
    >
      <path d={geo.path} fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinejoin="round"
            strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      {geo.dots.length > 0 ? (() => {
        const last = geo.dots[geo.dots.length - 1];
        return last ? <circle cx={last.x} cy={last.y} r="2" fill="currentColor" /> : null;
      })() : null}
    </svg>
  );
}
