/**
 * Menivor depth: "projector light". Surfaces sit on the ink page like frames on
 * a light table: a faint warm top edge (light spilling over the frame) and a
 * soft, deep drop. Values are Menivor's own; nothing here is shared with other
 * apps.
 */
import type { BoxShadowValue } from "react-native";

type Layer = Exclude<BoxShadowValue, string>;

/** Warm edge highlight that reads as light catching the top of a frame. */
const warmEdge: Layer = {
  offsetX: 0,
  offsetY: 1,
  blurRadius: 0,
  spreadDistance: 0,
  color: "rgba(255, 236, 196, 0.06)",
  inset: true,
};

/** Card / frame depth on the ink page. */
export const frameDepth: Layer[] = [
  warmEdge,
  { offsetX: 0, offsetY: 1, blurRadius: 2, spreadDistance: 0, color: "rgba(0, 0, 0, 0.30)" },
  { offsetX: 0, offsetY: 12, blurRadius: 30, spreadDistance: -6, color: "rgba(0, 0, 0, 0.45)" },
];

/** Raised gold action that presses into the page. */
export function goldPressDepth(pressed: boolean): Layer[] {
  if (pressed) {
    return [
      { offsetX: 0, offsetY: 2, blurRadius: 5, spreadDistance: 0, color: "rgba(0, 0, 0, 0.35)", inset: true },
    ];
  }
  return [
    { offsetX: 0, offsetY: 1, blurRadius: 0, spreadDistance: 0, color: "rgba(255, 255, 255, 0.22)", inset: true },
    { offsetX: 0, offsetY: 8, blurRadius: 22, spreadDistance: -6, color: "rgba(230, 199, 106, 0.28)" },
  ];
}
