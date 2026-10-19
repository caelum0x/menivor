/**
 * Niche scenes for Menivor's code-drawn reel art (no stock photos). Each niche
 * has a calm three-stop light palette and a subject shape; the art is pure
 * gradients and geometry so every tile is original and costs no assets.
 */

export type SceneShape = "sun" | "steam" | "pulse" | "window" | "grid" | "wave";

export interface NicheScene {
  readonly niche: string;
  /** Top, middle, bottom gradient stops. */
  readonly light: readonly [string, string, string];
  readonly shape: SceneShape;
  /** A short on-screen caption line for the tile. */
  readonly caption: string;
  /** Index of the highlighted word in `caption`. */
  readonly highlight: number;
}

export const NICHE_SCENES: readonly NicheScene[] = [
  { niche: "Travel", light: ["#3a2f4a", "#a0645a", "#e3b27a"], shape: "sun", caption: "one golden hour in Lisbon", highlight: 1 },
  { niche: "Cooking", light: ["#1f2a24", "#4f6b4f", "#c9a76b"], shape: "steam", caption: "stop crushing your herbs", highlight: 1 },
  { niche: "Fitness", light: ["#1b2433", "#35567a", "#9fc0c9"], shape: "pulse", caption: "mobility in 30 seconds", highlight: 2 },
  { niche: "Product demo", light: ["#16161c", "#2c2d45", "#7d7fb8"], shape: "grid", caption: "we deleted six screens", highlight: 2 },
  { niche: "Real estate", light: ["#22201c", "#6b5a45", "#d9c3a0"], shape: "window", caption: "wait for the window", highlight: 3 },
  { niche: "Baking", light: ["#2a1f1a", "#7a4f36", "#e0b98a"], shape: "wave", caption: "it is the fold", highlight: 3 },
  { niche: "Beauty", light: ["#2b1d26", "#7a4c63", "#e4b9c4"], shape: "sun", caption: "two minute glow routine", highlight: 2 },
  { niche: "Coaching", light: ["#1a2226", "#3f5d5b", "#b9d1c2"], shape: "wave", caption: "say it in one breath", highlight: 3 },
];

/** Stable string hash (djb2) so the same seed always draws the same scene. */
export function seedHash(seed: string): number {
  let hash = 5381;
  for (let i = 0; i < seed.length; i += 1) {
    hash = ((hash << 5) + hash + seed.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

/** Pick the scene for a niche name, or a stable one for any other seed. */
export function sceneFor(seed: string, niche?: string): NicheScene {
  const named = niche
    ? NICHE_SCENES.find((scene) => scene.niche.toLowerCase() === niche.toLowerCase())
    : undefined;
  if (named) return named;
  return NICHE_SCENES[seedHash(seed) % NICHE_SCENES.length] as NicheScene;
}
