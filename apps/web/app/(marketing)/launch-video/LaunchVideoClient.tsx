"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { signUpHref } from "@/lib/auth-redirect";
import { useSignedInState } from "@/lib/auth-state";
import { offersFromPlanConfig } from "@/lib/seo/entity";
import { useApiToken } from "@/lib/use-api-token";
import { apiRequest } from "@/src/shared/api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export const TOKEN_STORAGE_KEY = "menivor:partner-launch-token";

export interface LaunchVideoClientProps {
  readonly appUrl: string;
  readonly appName: string;
  readonly source: "scribase" | "rally";
}

export interface DraftBrief {
  readonly app_url: string;
  readonly app_name: string;
  readonly topic: string;
  readonly create_url: string;
  readonly source: string;
}

/** Reads the partner token from the URL fragment (or query), keeps it for this tab only, and strips it from the address bar. */
export function takePartnerToken(win: Window = window): string {
  const fromHash = new URLSearchParams(win.location.hash.replace(/^#/, "")).get("token") ?? "";
  const url = new URL(win.location.href);
  const fromQuery = url.searchParams.get("token") ?? "";
  const token = (fromHash || fromQuery).trim();
  try {
    if (token) {
      win.sessionStorage.setItem(TOKEN_STORAGE_KEY, token);
      url.searchParams.delete("token");
      url.hash = "";
      win.history.replaceState(null, "", url.pathname + url.search);
      return token;
    }
    return win.sessionStorage.getItem(TOKEN_STORAGE_KEY) ?? "";
  } catch {
    return token;
  }
}

export function startLaunchVideo(
  body: { token: string; app_url: string; app_name: string; source: string },
  token: string | undefined,
): Promise<DraftBrief> {
  return apiRequest<DraftBrief>("/partners/launch-video", { method: "POST", body, options: { token } });
}

function refusalMessage(err: unknown): string {
  const detail = (err as { detail?: { data?: { code?: string } } } | null)?.detail;
  const code = detail && typeof detail === "object" ? detail.data?.code : undefined;
  if (code === "expired" || code === "revoked") return "This link has expired. Open it again from Scribase.";
  if (code === "wrong_audience" || code === "wrong_capability") return "This link is not for a launch video.";
  return friendlyErrorMessage(err, "We could not open this launch video link.");
}

export function LaunchVideoClient({ appUrl, appName, source }: LaunchVideoClientProps) {
  const router = useRouter();
  const { isLoaded, isSignedIn } = useSignedInState();
  const getApiToken = useApiToken();
  const [partnerToken, setPartnerToken] = React.useState("");
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const started = React.useRef(false);
  const offers = React.useMemo(() => offersFromPlanConfig(), []);
  const card = offers.find((o) => o.name === "Card check");
  const pack = offers.find((o) => o.name !== "Card check" && !o.name.includes("monthly"));

  React.useEffect(() => {
    setPartnerToken(takePartnerToken());
  }, []);

  React.useEffect(() => {
    if (!isLoaded || !isSignedIn || !partnerToken || started.current) return;
    started.current = true;
    setBusy(true);
    void (async () => {
      try {
        const brief = await startLaunchVideo(
          { token: partnerToken, app_url: appUrl, app_name: appName, source },
          await getApiToken(),
        );
        try {
          window.sessionStorage.removeItem(TOKEN_STORAGE_KEY);
        } catch {
          // Storage blocked: the token expires on its own.
        }
        router.push(brief.create_url);
      } catch (err) {
        setError(refusalMessage(err));
        setBusy(false);
      }
    })();
  }, [isLoaded, isSignedIn, partnerToken, appUrl, appName, source, getApiToken, router]);

  const returnTo = `/launch-video?${new URLSearchParams({ app_url: appUrl, app_name: appName, source }).toString()}`;
  const label = appName || appUrl || "your app";

  return (
    <div className="space-y-6">
      <div>
        <p className="kicker text-muted-foreground">Launch video</p>
        <h1 className="mt-4 text-display-lg font-bold">A launch video for {label}</h1>
        <p className="mt-4 text-pretty text-lg leading-relaxed text-muted-foreground">
          Menivor turns your app&apos;s link into three vertical reels with different opening hooks, an AI
          voiceover and word-by-word captions. Your link is filled in for you.
        </p>
      </div>

      {!partnerToken ? (
        <p role="alert" className="text-sm text-destructive">
          This page opens from a link in Scribase. Open it again from there.
        </p>
      ) : error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : isLoaded && !isSignedIn ? (
        <div className="space-y-2">
          <Button asChild size="lg">
            <a href={signUpHref(returnTo)}>Sign up with your email to start</a>
          </Button>
          <p className="text-xs text-muted-foreground">
            Only the email you type here is used. Nothing else comes over from Scribase.
          </p>
        </div>
      ) : (
        <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
          {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
          Opening your launch video...
        </p>
      )}

      {card || pack ? (
        <p className="text-sm text-muted-foreground" data-copy-source="lib/seo/entity.ts offersFromPlanConfig">
          Pricing is the same as for everyone:
          {card ? ` a $${Number(card.price)} card check unlocks your free reels` : ""}
          {card && pack ? ", then" : ""}
          {pack ? ` packs from $${Number(pack.price)} or a monthly plan` : ""}.
        </p>
      ) : null}
    </div>
  );
}
