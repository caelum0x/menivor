import * as React from "react";
/** Caption safe-zone overlay (per-platform lower-third band) over a 9:16 preview. */
export function SafeZoneOverlay({ yFrac = 0.62, heightFrac = 0.14 }: { yFrac?: number; heightFrac?: number }) {
  return (
    <div style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
      <div style={{ position: "absolute", left: 0, right: 0, top: `${yFrac * 100}%`, height: `${heightFrac * 100}%`,
        border: "1px dashed rgba(106,91,255,0.7)", background: "rgba(106,91,255,0.08)" }} />
    </div>
  );
}
