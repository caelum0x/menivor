/**
 * `@reelforge/caption-engine` — word timestamps → styled ASS subtitles.
 *
 * Byte-identical to the Python port (`reelforge_caption_engine`, golden `.ass`
 * parity) so the client caption preview and the burned subtitle match exactly.
 */

export { hexToAss } from "./color.js";
export {
  buildAss,
  formatTime,
  PLAY_RES_X,
  PLAY_RES_Y,
  type Word,
} from "./ass.js";
export {
  getPreset,
  listPresets,
  type CaptionStyle,
} from "./style.js";
