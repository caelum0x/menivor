/**
 * Watches the real reels-made count and returns a one-time win when it
 * passes a milestone. The celebrated level persists per device; storage
 * errors mean "no celebration", never an error surface.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useCallback, useEffect, useState } from "react";

import { initialBaseline, reelLevel, reelWin, type ReelWin } from "./reel-wins";

const KEY = "menivor.reelWins.level.v1";

export function useReelWins(count: number | null): { win: ReelWin | null; dismiss: () => void } {
  const [win, setWin] = useState<ReelWin | null>(null);

  useEffect(() => {
    if (count === null) return;
    let active = true;
    void (async () => {
      try {
        const raw = await AsyncStorage.getItem(KEY);
        if (!active) return;
        if (raw === null) {
          const base = initialBaseline(count);
          await AsyncStorage.setItem(KEY, String(base));
          const first = reelWin(base, count);
          if (first && active) {
            setWin(first);
            await AsyncStorage.setItem(KEY, String(first.level));
          }
          return;
        }
        const baseline = Number.parseInt(raw, 10) || 0;
        const next = reelWin(baseline, count);
        if (next && active) {
          setWin(next);
          await AsyncStorage.setItem(KEY, String(reelLevel(count)));
        }
      } catch {
        // A celebration is a bonus; never surface storage errors.
      }
    })();
    return () => {
      active = false;
    };
  }, [count]);

  const dismiss = useCallback(() => setWin(null), []);
  return { win, dismiss };
}
