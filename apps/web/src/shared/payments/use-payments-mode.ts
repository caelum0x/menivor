"use client";

import * as React from "react";
import type { PaymentsMode } from "@/lib/types";
import { DEFAULT_PAYMENTS_MODE, loadPaymentsMode } from "./mode";

export interface PaymentsModeState {
  readonly loaded: boolean;
  readonly mode: PaymentsMode;
}

/** Current payments mode (defaults to "open" until the status loads). */
export function usePaymentsMode(): PaymentsModeState {
  const [state, setState] = React.useState<PaymentsModeState>({
    loaded: false,
    mode: DEFAULT_PAYMENTS_MODE,
  });
  React.useEffect(() => {
    let cancelled = false;
    void loadPaymentsMode().then((mode) => {
      if (!cancelled) setState({ loaded: true, mode });
    });
    return () => {
      cancelled = true;
    };
  }, []);
  return state;
}
