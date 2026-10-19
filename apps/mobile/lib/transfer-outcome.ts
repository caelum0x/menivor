/**
 * Whether an HTTP response proves a transfer command did not mutate Mint.
 *
 * Unknown outcomes retain their stable pending key. That includes 408, 425,
 * 429, every 5xx response and transport/invalid-response failures (status 0).
 */
const DEFINITIVE_TRANSFER_FAILURE_STATUSES = new Set([
  400, 401, 402, 403, 404, 409, 410, 422,
]);

export function isDefinitiveTransferFailureStatus(status: number): boolean {
  return DEFINITIVE_TRANSFER_FAILURE_STATUSES.has(status);
}
