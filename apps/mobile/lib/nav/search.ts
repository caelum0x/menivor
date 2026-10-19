/**
 * Pure, dependency-free search/ranking over the navigation registry.
 *
 * The navigation hub uses this to turn a free-text query into a ranked, flat
 * list of screens drawn from every group. Keeping the logic pure (no React, no
 * fetch) makes it trivial to unit-test and reuse.
 *
 * Ranking (higher = better):
 *   4  title starts with the query
 *   3  a title word starts with the query
 *   2  title contains the query
 *   1  subtitle / group / keyword contains the query
 * A screen must match every whitespace-separated term to be included.
 */

import type { ScreenMeta } from "./registry";

/** A screen paired with its match score for a given query. */
export interface RankedScreen {
  screen: ScreenMeta;
  score: number;
}

function haystackFor(screen: ScreenMeta): {
  title: string;
  rest: string;
} {
  const title = screen.title.toLowerCase();
  const rest = [
    screen.subtitle ?? "",
    screen.group,
    ...(screen.keywords ?? []),
  ]
    .join(" ")
    .toLowerCase();
  return { title, rest };
}

/** Score a single screen against one already-lowercased term. 0 = no match. */
function scoreTerm(screen: ScreenMeta, term: string): number {
  const { title, rest } = haystackFor(screen);

  if (title.startsWith(term)) return 4;
  if (title.split(/\s+/).some((word) => word.startsWith(term))) return 3;
  if (title.includes(term)) return 2;
  if (rest.includes(term)) return 1;
  return 0;
}

/**
 * Return the screens matching `query`, ranked best-first. An empty/whitespace
 * query returns an empty list (callers should show the grouped view instead).
 * Every term in the query must match (AND semantics).
 */
export function searchScreens(
  query: string,
  screens: readonly ScreenMeta[],
): readonly RankedScreen[] {
  const terms = query
    .trim()
    .toLowerCase()
    .split(/\s+/)
    .filter((t) => t.length > 0);

  if (terms.length === 0) return [];

  const ranked: RankedScreen[] = [];
  for (const screen of screens) {
    if (screen.hidden) continue;

    let total = 0;
    let matchedEvery = true;
    for (const term of terms) {
      const s = scoreTerm(screen, term);
      if (s === 0) {
        matchedEvery = false;
        break;
      }
      total += s;
    }

    if (matchedEvery) ranked.push({ screen, score: total });
  }

  return ranked.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    return a.screen.title.localeCompare(b.screen.title);
  });
}
