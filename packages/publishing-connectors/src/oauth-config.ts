/** Per-platform OAuth endpoint / scope descriptors (mirror of `oauth_config.py`). */

export interface OAuthConfig {
  auth_url: string;
  token_url: string;
  scopes: string[];
  pkce: boolean;
}

export const OAUTH: Record<string, OAuthConfig> = {
  tiktok: {
    auth_url: "https://www.tiktok.com/v2/auth/authorize/",
    token_url: "https://open.tiktokapis.com/v2/oauth/token/",
    scopes: ["user.info.basic", "video.publish", "video.upload"],
    pkce: true,
  },
  instagram: {
    auth_url: "https://www.facebook.com/v19.0/dialog/oauth",
    token_url: "https://graph.facebook.com/v19.0/oauth/access_token",
    scopes: ["instagram_basic", "instagram_content_publish", "pages_show_list"],
    pkce: false,
  },
  youtube: {
    auth_url: "https://accounts.google.com/o/oauth2/v2/auth",
    token_url: "https://oauth2.googleapis.com/token",
    scopes: ["https://www.googleapis.com/auth/youtube.upload"],
    pkce: true,
  },
  x: {
    auth_url: "https://twitter.com/i/oauth2/authorize",
    token_url: "https://api.twitter.com/2/oauth2/token",
    scopes: ["tweet.read", "tweet.write", "users.read", "offline.access"],
    pkce: true,
  },
};

export function oauthFor(platform: string): OAuthConfig | undefined {
  return OAUTH[String(platform || "").trim().toLowerCase()];
}

export function scopeString(platform: string): string {
  const cfg = oauthFor(platform);
  return cfg ? cfg.scopes.join(" ") : "";
}

export function requiresPkce(platform: string): boolean {
  return Boolean(oauthFor(platform)?.pkce);
}
