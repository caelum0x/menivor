"use client";

import * as React from "react";

import { useRequestOptions } from "@/src/features/ad-studio/shared";
import type { RequestOptions } from "@/src/shared/api";

/** Request options whose identity never changes, so load effects run once (not on every auth re-render). */
export function useStableRequestOptions(): () => Promise<RequestOptions> {
  const requestOptions = useRequestOptions();
  const ref = React.useRef(requestOptions);
  ref.current = requestOptions;
  return React.useCallback(() => ref.current(), []);
}
