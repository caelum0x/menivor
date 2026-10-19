export interface ResourceRequestOptions {
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined>;
  headers?: Record<string, string>;
}

/** Internal transport contract consumed by public resource modules. */
export type Requester = <T>(
  method: string,
  path: string,
  options?: ResourceRequestOptions,
) => Promise<T>;
