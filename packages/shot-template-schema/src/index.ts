/**
 * `@reelforge/shot-template-schema` — genre templates as named segment slots
 * (Hook / Proof / Payoff / Loop) with validation + deterministic instance
 * hashing. Byte-identical to the Python port (`reelforge_shot_template`, golden
 * fixtures) so the `templates/` domain, the pickers, and render-core all agree.
 */

export { ROLE_ORDER, isRole, roleIndex, type SlotRole } from "./roles.js";
export {
  makeSlot,
  makeTemplate,
  validateTemplate,
  totalDurationMs,
  contentHash,
  type SegmentSlot,
  type ShotTemplate,
} from "./template.js";
export { getPreset, listPresets } from "./presets.js";
