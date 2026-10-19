/** A real count that rolls up to its new value (instant under Reduce Motion). */
import { useEffect, useRef, useState } from "react";
import { Text, type StyleProp, type TextStyle } from "react-native";

import { useReduceMotion } from "./useReduceMotion";

const MAX_MS = 900;

export interface ReelCounterProps {
  readonly value: number;
  readonly style?: StyleProp<TextStyle>;
}

export function ReelCounter({ value, style }: ReelCounterProps) {
  const reduceMotion = useReduceMotion();
  const safe = Number.isFinite(value) ? Math.round(value) : 0;
  const [shown, setShown] = useState(safe);
  const shownRef = useRef(safe);

  useEffect(() => {
    const from = shownRef.current;
    if (reduceMotion || from === safe) {
      shownRef.current = safe;
      setShown(safe);
      return undefined;
    }
    const duration = Math.min(MAX_MS, 240 + Math.abs(safe - from) * 60);
    const start = Date.now();
    let frame = 0;
    const tick = () => {
      const t = Math.min(1, (Date.now() - start) / duration);
      const eased = 1 - (1 - t) * (1 - t);
      const next = Math.round(from + (safe - from) * eased);
      shownRef.current = next;
      setShown(next);
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [reduceMotion, safe]);

  return (
    <Text style={style} accessibilityLabel={String(safe)}>
      {shown}
    </Text>
  );
}
