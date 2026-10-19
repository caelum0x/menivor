"use client";

import * as React from "react";
import { storePendingReferral } from "./referral-capture";

/** Persists `?ref=` from the sign-up URL so onboarding can redeem it. */
export function ReferralCapture({ code }: Readonly<{ code: string }>) {
  React.useEffect(() => {
    storePendingReferral(code);
  }, [code]);
  return null;
}
