/**
 * Chop (the Menivor desktop editor) release lookup for the /editor page.
 *
 * The installers are built and published by the desktop repository's
 * `.github/workflows/build.yml` (dmg, msi / setup.exe, AppImage, deb, rpm).
 * Every push to main publishes a `v<version>-alpha.<n>` PRE-release, so
 * GitHub's `/releases/latest` (which skips pre-releases) is not enough: this
 * reads the newest non-draft release that actually carries installers.
 *
 * The fetch is server-side with ISR revalidation, so the page stays static
 * and GitHub's unauthenticated rate limit is spent once an hour, not per
 * visitor. When no public release exists (the repository is private or has not
 * published yet) the lookup returns `null` and the page says so plainly.
 */

/**
 * `owner/name` of the repository whose releases carry the installers. The
 * repository keeps its upstream name internally; users only ever see "Chop".
 */
export const EDITOR_RELEASES_REPO: string =
  process.env.EDITOR_RELEASES_REPO?.trim() ||
  process.env.WOLFCUT_RELEASES_REPO?.trim() ||
  "caelum0x/wolfcut";

const EDITOR_REPO_URL = `https://github.com/${EDITOR_RELEASES_REPO}`;

/** Seconds between GitHub lookups. */
export const EDITOR_RELEASES_REVALIDATE_S = 3600;

export type EditorPlatform = "macos" | "windows" | "linux";

export interface EditorAsset {
  readonly platform: EditorPlatform;
  /** Human label, e.g. "macOS (Apple silicon)". */
  readonly label: string;
  /** Installer format, e.g. "dmg", "msi", "AppImage". */
  readonly format: string;
  readonly name: string;
  readonly url: string;
  readonly sizeBytes: number;
}

export interface EditorRelease {
  readonly tag: string;
  readonly name: string;
  readonly prerelease: boolean;
  readonly publishedAt: string | null;
  readonly htmlUrl: string;
  readonly assets: readonly EditorAsset[];
}

interface GitHubAsset {
  readonly name?: unknown;
  readonly browser_download_url?: unknown;
  readonly size?: unknown;
}

interface GitHubRelease {
  readonly tag_name?: unknown;
  readonly name?: unknown;
  readonly draft?: unknown;
  readonly prerelease?: unknown;
  readonly published_at?: unknown;
  readonly html_url?: unknown;
  readonly assets?: unknown;
}

const FORMATS: ReadonlyArray<{
  readonly suffix: string;
  readonly platform: EditorPlatform;
  readonly format: string;
}> = [
  { suffix: ".dmg", platform: "macos", format: "dmg" },
  { suffix: "-setup.exe", platform: "windows", format: "setup.exe" },
  { suffix: ".exe", platform: "windows", format: "exe" },
  { suffix: ".msi", platform: "windows", format: "msi" },
  { suffix: ".appimage", platform: "linux", format: "AppImage" },
  { suffix: ".deb", platform: "linux", format: "deb" },
  { suffix: ".rpm", platform: "linux", format: "rpm" },
];

const PLATFORM_NAMES: Readonly<Record<EditorPlatform, string>> = {
  macos: "macOS",
  windows: "Windows",
  linux: "Linux",
};

/** The CPU a bundle targets, from Tauri's file-name conventions. */
function archOf(name: string, platform: EditorPlatform): string {
  const lower = name.toLowerCase();
  if (/(aarch64|arm64)/.test(lower)) {
    return platform === "macos" ? "Apple silicon" : "ARM64";
  }
  if (/(x86_64|x64|amd64)/.test(lower)) {
    return platform === "macos" ? "Intel" : "x64";
  }
  return "";
}

/** Maps one GitHub asset to an installer, or null for checksums/manifests. */
export function classifyAsset(asset: GitHubAsset): EditorAsset | null {
  const name = typeof asset.name === "string" ? asset.name : "";
  const url =
    typeof asset.browser_download_url === "string" ? asset.browser_download_url : "";
  if (!name || !url.startsWith("https://")) return null;
  const lower = name.toLowerCase();
  const match = FORMATS.find((entry) => lower.endsWith(entry.suffix));
  if (!match) return null;
  const arch = archOf(name, match.platform);
  return {
    platform: match.platform,
    label: arch ? `${PLATFORM_NAMES[match.platform]} (${arch})` : PLATFORM_NAMES[match.platform],
    format: match.format,
    name,
    url,
    sizeBytes: typeof asset.size === "number" && asset.size > 0 ? asset.size : 0,
  };
}

/** Picks the newest non-draft release with at least one installer. */
export function pickRelease(releases: readonly GitHubRelease[]): EditorRelease | null {
  for (const release of releases) {
    if (release.draft === true) continue;
    const assets = Array.isArray(release.assets)
      ? (release.assets as GitHubAsset[])
          .map(classifyAsset)
          .filter((asset): asset is EditorAsset => asset !== null)
      : [];
    if (assets.length === 0) continue;
    const tag = typeof release.tag_name === "string" ? release.tag_name : "";
    return {
      tag,
      name: typeof release.name === "string" && release.name ? release.name : tag,
      prerelease: release.prerelease === true,
      publishedAt: typeof release.published_at === "string" ? release.published_at : null,
      htmlUrl:
        typeof release.html_url === "string" ? release.html_url : `${EDITOR_REPO_URL}/releases`,
      assets,
    };
  }
  return null;
}

/**
 * The newest downloadable editor release, or null when none is public.
 * Never throws: a GitHub outage renders the page's no-release state.
 */
export async function getLatestEditorRelease(): Promise<EditorRelease | null> {
  try {
    const response = await fetch(
      `https://api.github.com/repos/${EDITOR_RELEASES_REPO}/releases?per_page=10`,
      {
        headers: {
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "User-Agent": "menivor-web",
        },
        next: { revalidate: EDITOR_RELEASES_REVALIDATE_S },
      },
    );
    if (!response.ok) return null;
    const body: unknown = await response.json();
    return Array.isArray(body) ? pickRelease(body as GitHubRelease[]) : null;
  } catch {
    return null;
  }
}

/** Browser OS from a User-Agent header, for picking the one Download button. */
export function platformFromUserAgent(userAgent: string | null | undefined): EditorPlatform | null {
  const ua = (userAgent ?? "").toLowerCase();
  if (!ua || /(iphone|ipad|android)/.test(ua)) return null;
  if (ua.includes("mac os x") || ua.includes("macintosh")) return "macos";
  if (ua.includes("windows")) return "windows";
  if (ua.includes("linux") || ua.includes("x11")) return "linux";
  return null;
}

/** Preferred installer format per platform (first match wins). */
const PREFERRED_FORMATS: Readonly<Record<EditorPlatform, readonly string[]>> = {
  macos: ["dmg"],
  windows: ["setup.exe", "msi", "exe"],
  linux: ["AppImage", "deb", "rpm"],
};

/**
 * The single installer to offer: the visitor's platform first (Apple silicon
 * before Intel on macOS), otherwise the first platform the release carries.
 */
export function primaryAsset(
  release: EditorRelease,
  platform: EditorPlatform | null,
): EditorAsset | null {
  const order: readonly EditorPlatform[] = platform
    ? [platform, ...(["macos", "windows", "linux"] as const).filter((p) => p !== platform)]
    : ["macos", "windows", "linux"];
  for (const candidate of order) {
    const assets = release.assets.filter((asset) => asset.platform === candidate);
    for (const format of PREFERRED_FORMATS[candidate]) {
      const matches = assets.filter((asset) => asset.format === format);
      const best = matches.find((asset) => /apple silicon/i.test(asset.label)) ?? matches[0];
      if (best) return best;
    }
  }
  return null;
}

/** "84 MB" style size for a download button. */
export function formatBytes(bytes: number): string {
  if (bytes <= 0) return "";
  const mb = bytes / (1024 * 1024);
  return mb >= 10 ? `${Math.round(mb)} MB` : `${mb.toFixed(1)} MB`;
}
