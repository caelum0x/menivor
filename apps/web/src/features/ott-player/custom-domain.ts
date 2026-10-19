/**
 * Custom domains for storefronts (MV4, OD-MV9): a request on a host that is not
 * ours is rewritten to that channel's storefront. Only while the storefront is
 * live; lookups are cached for five minutes per host.
 */

const TTL_MS = 5 * 60 * 1000;
const cache = new Map<string, { handle: string | null; at: number }>();

export function firstPartyHosts(raw: string | undefined = process.env.NEXT_PUBLIC_FIRST_PARTY_HOSTS): Set<string> {
  const base = ["menivor.com", "www.menivor.com", "localhost", "127.0.0.1"];
  return new Set([...base, ...(raw ?? "").split(",").map((h) => h.trim().toLowerCase()).filter(Boolean)]);
}

export function isCustomHost(host: string, hosts: Set<string> = firstPartyHosts()): boolean {
  const bare = host.toLowerCase().split(":")[0] ?? "";
  if (!bare || hosts.has(bare)) return false;
  return !bare.endsWith(".workers.dev") && !bare.endsWith(".menivor.com");
}

export async function handleForHost(
  host: string,
  lookup: (host: string) => Promise<{ handle: string } | null>,
  now: number = Date.now(),
): Promise<string | null> {
  const bare = host.toLowerCase().split(":")[0] ?? "";
  const hit = cache.get(bare);
  if (hit && now - hit.at < TTL_MS) return hit.handle;
  let handle: string | null = null;
  try {
    handle = (await lookup(bare))?.handle ?? null;
  } catch {
    handle = null;
  }
  cache.set(bare, { handle, at: now });
  return handle;
}

/** The storefront path for a custom-domain request path ("/" -> the channel, "/<id>" -> a title). */
export function rewritePath(handle: string, pathname: string): string {
  const rest = pathname === "/" ? "" : pathname;
  return `/c/${encodeURIComponent(handle)}${rest}`;
}
