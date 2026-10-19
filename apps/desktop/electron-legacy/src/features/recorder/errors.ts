/**
 * A single, typed error surface for the recorder so the UI can react to *why* a
 * capture failed (permission denied vs. no source vs. cancelled) instead of
 * pattern-matching raw `DOMException` names in components.
 */

export type RecorderErrorCode =
  | "permission-denied"
  | "no-source"
  | "cancelled"
  | "not-supported"
  | "capture-failed"
  | "unknown";

/** Error thrown/emitted by the recorder, carrying a machine-readable `code`. */
export class RecorderError extends Error {
  readonly code: RecorderErrorCode;

  constructor(code: RecorderErrorCode, message: string) {
    super(message);
    this.name = "RecorderError";
    this.code = code;
  }
}

/** Type guard for narrowing an unknown error to a {@link RecorderError}. */
export function isRecorderError(value: unknown): value is RecorderError {
  return value instanceof RecorderError;
}

/**
 * Normalise any thrown value from the capture APIs into a {@link RecorderError}
 * with a user-facing message. `getDisplayMedia`/`getUserMedia` reject with
 * `DOMException`s whose `name` tells us what went wrong.
 */
export function toRecorderError(value: unknown): RecorderError {
  if (isRecorderError(value)) return value;

  if (value instanceof DOMException) {
    switch (value.name) {
      case "NotAllowedError":
        // Chromium raises this both when the OS/user denies the permission and
        // when the native picker is dismissed — cover both in one message.
        return new RecorderError(
          "permission-denied",
          "Screen recording permission was denied or the picker was dismissed. " +
            "Grant access under System Settings › Privacy & Security › Screen Recording, then try again.",
        );
      case "NotFoundError":
        return new RecorderError(
          "no-source",
          "No screen or window was available to record.",
        );
      case "AbortError":
        return new RecorderError("cancelled", "Screen selection was cancelled.");
      case "NotReadableError":
        return new RecorderError(
          "capture-failed",
          "The selected screen or window could not be captured. Another app may be using it.",
        );
      case "NotSupportedError":
        return new RecorderError(
          "not-supported",
          "Screen recording is not supported in this environment.",
        );
      default:
        return new RecorderError("unknown", value.message || "Recording failed.");
    }
  }

  if (value instanceof Error) {
    return new RecorderError("unknown", value.message || "Recording failed.");
  }

  return new RecorderError("unknown", "An unexpected recording error occurred.");
}
