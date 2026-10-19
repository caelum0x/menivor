/**
 * `@reelforge/trends-schema` — trend DTOs + pure saturation/velocity/decay/
 * opportunity scoring, bit-identical to the Python port (`reelforge_trends`,
 * golden fixtures) so the trend feed scores the same on api, web and mobile.
 */

export {
  saturation,
  velocity,
  decay,
  opportunity,
  score,
  adSafe,
  clamp01,
  round6,
  type TrendScore,
  type SoundFlags,
} from "./scoring.js";
