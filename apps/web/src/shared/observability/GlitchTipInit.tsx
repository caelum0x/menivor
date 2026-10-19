"use client";

import * as React from "react";
import { initGlitchTip } from "./glitchtip";

/** Mount once in the root layout. Renders nothing. */
export function GlitchTipInit() {
  React.useEffect(() => {
    initGlitchTip(
      process.env.NEXT_PUBLIC_GLITCHTIP_DSN,
      process.env.NEXT_PUBLIC_GLITCHTIP_RELEASE || undefined,
    );
  }, []);
  return null;
}
