/**
 * Normalises an unknown thrown value into a user-facing message. Prefers the
 * backend envelope message carried by {@link ApiError}, then any Error message,
 * with a safe generic fallback.
 */

import { ApiError } from "@/lib/api";

export function describeError(err: unknown, fallback = "Something went wrong."): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return fallback;
}
