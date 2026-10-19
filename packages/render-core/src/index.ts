/**
 * `@reelforge/render-core` — declarative RenderSpec → FFmpeg filtergraph.
 *
 * Byte-identical to the Python port (`reelforge_render_core`, golden fixtures)
 * so the client preview and the executor (`compose_ffmpeg.py`) build the same
 * composition graph. This package owns spec→string only; the Celery worker
 * spawns FFmpeg.
 */

export {
  buildFiltergraph,
  buildVideoGraph,
  buildAudioGraph,
  videoOutLabel,
  hasAudioOut,
  AVATAR_LAYOUTS,
  type RenderSpec,
  type RenderLayout,
  type RenderAvatar,
} from "./filtergraph.js";
export {
  makeSpec,
  validateSpec,
  type MakeSpecOptions,
} from "./spec.js";
