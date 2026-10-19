/** Menivor surface depth (projector light), mapped for the shared UI primitives. */
import type { ViewStyle } from "react-native";

import { frameDepth, goldPressDepth } from "@/src/ui/menivor/depth";

/** Frame depth for cards on the ink page. */
export const softCardDepth: ViewStyle = { boxShadow: frameDepth };

/** Raised primary button; presses into the page while held. */
export function softButtonDepth(_fill: string, pressed: boolean): ViewStyle {
  return { boxShadow: goldPressDepth(pressed) };
}
