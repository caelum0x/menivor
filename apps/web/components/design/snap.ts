/** Snap guides: align a moving box's edges/centre to the page and to other layers. */

export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface SnapResult {
  x: number;
  y: number;
  /** Guide positions in page units (vertical lines at x, horizontal lines at y). */
  guidesX: number[];
  guidesY: number[];
}

function best(points: number[], targets: number[], threshold: number): { delta: number; at: number } | null {
  let found: { delta: number; at: number } | null = null;
  for (const p of points) {
    for (const t of targets) {
      const d = t - p;
      if (Math.abs(d) <= threshold && (!found || Math.abs(d) < Math.abs(found.delta))) found = { delta: d, at: t };
    }
  }
  return found;
}

export function snapBox(box: Box, others: Box[], page: { width: number; height: number }, threshold: number): SnapResult {
  const xs = [0, page.width / 2, page.width];
  const ys = [0, page.height / 2, page.height];
  for (const o of others) {
    xs.push(o.x, o.x + o.width / 2, o.x + o.width);
    ys.push(o.y, o.y + o.height / 2, o.y + o.height);
  }
  const sx = best([box.x, box.x + box.width / 2, box.x + box.width], xs, threshold);
  const sy = best([box.y, box.y + box.height / 2, box.y + box.height], ys, threshold);
  return {
    x: box.x + (sx?.delta ?? 0),
    y: box.y + (sy?.delta ?? 0),
    guidesX: sx ? [sx.at] : [],
    guidesY: sy ? [sy.at] : [],
  };
}
