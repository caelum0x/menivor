import { app, safeStorage } from "electron";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

import type { ConfigPatch, PublicConfig } from "./ipc";

/**
 * Secure, main-process-only config store.
 *
 * The API base and the (optional) API token are persisted to a JSON file under
 * the OS `userData` directory. The token is encrypted at rest with Electron's
 * OS-backed {@link safeStorage} when available (Keychain / DPAPI / libsecret),
 * and is NEVER returned to the renderer — {@link ConfigStore.getPublic} only
 * reports whether a token is set. This is the only place a secret lives.
 */

const DEFAULT_API_BASE = "http://localhost:8080/api/v1";
const CONFIG_FILENAME = "reelforge-config.json";

/**
 * Hostnames the proxy is permitted to send the API token to. The renderer can
 * change `apiBase`, but it must resolve to one of these hosts — otherwise a
 * compromised/XSS'd renderer could point `apiBase` at an attacker and have main
 * attach the secret `x-api-key` to a request bound for that host. Defaults to
 * loopback (the bundled backend); override via `REELFORGE_API_ALLOWED_HOSTS`
 * (comma-separated hostnames) for a remote deployment. The renderer cannot
 * influence this env-derived allowlist.
 */
const DEFAULT_ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"];

function allowedHosts(): Set<string> {
  const fromEnv = (process.env.REELFORGE_API_ALLOWED_HOSTS ?? "")
    .split(",")
    .map((h) => h.trim().toLowerCase())
    .filter(Boolean);
  return new Set([...DEFAULT_ALLOWED_HOSTS, ...fromEnv]);
}

/** True when `apiBase`'s host is on the allowlist and may receive the token. */
export function isAllowedApiHost(apiBase: string): boolean {
  try {
    return allowedHosts().has(new URL(apiBase).hostname.toLowerCase());
  } catch {
    return false;
  }
}

/** On-disk shape. `tokenEnc` is base64: either safeStorage ciphertext or, as a
 *  last-resort fallback on platforms without encryption, plaintext bytes. */
interface StoredConfig {
  apiBase: string;
  tokenEnc: string | null;
  /** True when `tokenEnc` is OS-encrypted; false when it is plaintext fallback. */
  tokenEncrypted: boolean;
}

/** Normalise an API base: must be an absolute http(s) URL; trailing slashes are
 *  stripped. Returns null when invalid so the caller can reject the patch. */
export function normalizeApiBase(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  let url: URL;
  try {
    url = new URL(trimmed);
  } catch {
    return null;
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") return null;
  // The renderer must not be able to redirect the stored token to an arbitrary
  // host — pin `apiBase` to the approved host allowlist.
  if (!allowedHosts().has(url.hostname.toLowerCase())) return null;
  return trimmed.replace(/\/+$/, "");
}

export class ConfigStore {
  private readonly filePath: string;
  private cache: StoredConfig;

  constructor(filePath?: string) {
    this.filePath = filePath ?? join(app.getPath("userData"), CONFIG_FILENAME);
    this.cache = this.load();
  }

  private load(): StoredConfig {
    const fallback: StoredConfig = {
      apiBase: DEFAULT_API_BASE,
      tokenEnc: null,
      tokenEncrypted: false,
    };
    try {
      if (!existsSync(this.filePath)) return fallback;
      const parsed = JSON.parse(readFileSync(this.filePath, "utf8")) as Partial<StoredConfig>;
      const apiBase =
        typeof parsed.apiBase === "string"
          ? (normalizeApiBase(parsed.apiBase) ?? DEFAULT_API_BASE)
          : DEFAULT_API_BASE;
      return {
        apiBase,
        tokenEnc: typeof parsed.tokenEnc === "string" ? parsed.tokenEnc : null,
        tokenEncrypted: parsed.tokenEncrypted === true,
      };
    } catch {
      // Corrupt or unreadable config falls back to defaults rather than crashing.
      return fallback;
    }
  }

  private persist(): void {
    const dir = dirname(this.filePath);
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
    writeFileSync(this.filePath, JSON.stringify(this.cache, null, 2), {
      encoding: "utf8",
      mode: 0o600,
    });
  }

  /** Non-secret view for the renderer. */
  getPublic(): PublicConfig {
    return { apiBase: this.cache.apiBase, tokenSet: this.cache.tokenEnc !== null };
  }

  /** Decrypt and return the stored token (main-process use only). */
  getToken(): string | null {
    if (this.cache.tokenEnc === null) return null;
    const buf = Buffer.from(this.cache.tokenEnc, "base64");
    if (!this.cache.tokenEncrypted) return buf.toString("utf8");
    try {
      return safeStorage.decryptString(buf);
    } catch {
      return null;
    }
  }

  private setToken(token: string): void {
    if (safeStorage.isEncryptionAvailable()) {
      this.cache.tokenEnc = safeStorage.encryptString(token).toString("base64");
      this.cache.tokenEncrypted = true;
    } else {
      this.cache.tokenEnc = Buffer.from(token, "utf8").toString("base64");
      this.cache.tokenEncrypted = false;
    }
  }

  /**
   * Apply a validated patch. Throws on an invalid `apiBase`. An empty-string
   * `token` clears the stored token; a non-empty one replaces it; omitting the
   * field leaves it untouched. Returns the updated public config.
   */
  save(patch: ConfigPatch): PublicConfig {
    if (patch.apiBase !== undefined) {
      const normalized = normalizeApiBase(patch.apiBase);
      if (normalized === null) {
        throw new Error(
          "Invalid API base URL — must be an absolute http(s) URL on an approved host.",
        );
      }
      this.cache.apiBase = normalized;
    }

    if (patch.token !== undefined) {
      if (patch.token === "") {
        this.cache.tokenEnc = null;
        this.cache.tokenEncrypted = false;
      } else {
        this.setToken(patch.token);
      }
    }

    this.persist();
    return this.getPublic();
  }
}
