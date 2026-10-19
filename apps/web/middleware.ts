import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";
import { clerkProxyUrl, hasRealClerkKey } from "@/lib/clerk";
import { isClerkProxyPath, proxyClerkRequest } from "@/lib/clerk-proxy";
import { handleForHost, isCustomHost, rewritePath } from "@/src/features/ott-player/custom-domain";
import { resolveCustomDomain } from "@/src/features/ott-player/api";
import { ottStorefrontLive } from "@/src/features/ott-player/flags";

/**
 * Clerk auth middleware.
 *
 * DEVICE-SESSION-FIRST product: viewing/browsing surfaces (reels library,
 * jobs, public share/creator pages) stay PUBLIC — visitors get a zero-signup
 * device session (see `src/shared/device/session.ts`) whose `x-api-key` the
 * API authorizes, the same first-run flow as the mobile app. `/create` itself
 * now requires a signed-in account before it renders (see
 * `src/shared/access/use-web-access.ts`), and `/wallet` is a protected route
 * below — both used to be part of this public loop; keep this comment and the
 * route lists below in sync when that changes again. Clerk protection is kept
 * for the enterprise governance and account-only surfaces below; signing in
 * simply upgrades the credential the transport sends elsewhere.
 *
 * Note: `@clerk/nextjs` v6 replaces the legacy `authMiddleware` with
 * `clerkMiddleware` + `createRouteMatcher`; this is the equivalent, current
 * API for protecting the governance and account routes listed below.
 */
const isProtectedRoute = createRouteMatcher([
  // ENTERPRISE Access & Governance surfaces require a signed-in caller; the API
  // then hard-gates on membership role (/settings) or is_staff (/admin).
  "/settings(.*)",
  "/admin(.*)",
  // Post-sign-up onboarding and workspace subscriptions only make sense for a
  // real account (a device guest has no workspaces to bill); unauthenticated
  // visitors are sent to sign-in and returned here afterwards.
  "/onboarding(.*)",
  "/billing",
  // Account-only pages: every call they make needs a signed-in account, so a
  // signed-out visitor used to land on "Please sign in to continue." with a
  // Try again button that failed the same way. Send them to sign-in and back.
  "/account(.*)",
  "/wallet(.*)",
  "/spend(.*)",
  "/usage(.*)",
  "/notifications(.*)",
  "/connections(.*)",
  "/brand(.*)",
  "/agent(.*)",
  // Referrals: same "every call needs a signed-in account" shape as the
  // pages above. Was missing from this list (nav-items.ts groups it with
  // /account, /wallet, /notifications, /brand under Settings), so a
  // signed-out visitor hit the same dead "Try again" loop this comment
  // describes instead of being sent to sign-in.
  "/referral(.*)",
  // Wave 2: account-only creative surfaces (every call needs a signed-in account).
  "/review(.*)",
  "/competitors(.*)",
  "/ad-fatigue(.*)",
  "/actors(.*)",
  "/translate(.*)",
  "/workflows",
  "/workflows/(.*)",
  "/voices(.*)",
  "/performance(.*)",
  // Menivor Growth phase 2: keyword tracker (owner-scoped, per-account data).
  "/keywords(.*)",
  // Menivor Growth phase 3: launch kit (owner-scoped, per-account data).
  "/launch-kit(.*)",
  // Content Month: every call needs a signed-in account (plans are owner-scoped).
  "/month(.*)",
]);

/**
 * `/create` (the default topic-or-link flow) renders fully server-side
 * before `useWebAccess`'s client-side redirect ever runs, so a signed-out
 * visitor (or a client with JS disabled, or a bot) got a 200 with the full
 * compose UI instead of being sent to sign-up. It is gated like every other
 * account-only surface above, but kept out of `isProtectedRoute`: this is the
 * ONE route the homepage's own CTAs link straight into ("Make 3 reels" /
 * preset chips, copy: "Sign up in one click with Google or Apple and make
 * your first reel free, no card"). Clerk's default `auth.protect()` sends an
 * unauthenticated page request to `/sign-in` ("Welcome back. Sign in to
 * continue."), which is the wrong first message for someone who has never
 * had an account — it reads as "you already signed up, log back in" to a
 * brand-new visitor. Route this one straight to `/sign-up` instead, carrying
 * the full requested URL (including `?preset=`) as `redirect_url` so the
 * visitor lands back on the exact reel they picked. `/create/advanced` and
 * `/create/templates` stay public on purpose (hands-on tools, no account
 * needed to browse them).
 */
const isSignUpFirstRoute = createRouteMatcher(["/create"]);

/** `/sign-up?redirect_url=<original request>`, as an absolute URL for `auth.protect()`. */
function signUpRedirectUrl(req: NextRequest): string {
  const target = new URL("/sign-up", req.url);
  target.searchParams.set("redirect_url", req.url);
  return target.toString();
}

/**
 * Explicitly-public surfaces that must render for logged-out visitors:
 * `/r/{token}` is the public WATERMARKED share page and `/creators/*` are public
 * creator profiles + the leaderboard. Matched first so these never require auth
 * even if the protected list widens later.
 */
const isPublicRoute = createRouteMatcher(["/r/(.*)", "/creators/(.*)", "/c/(.*)", "/embed/(.*)"]);

/** Wave P PM2.5: a creator's own domain shows their channel (only while the storefront is live). */
async function customDomainRewrite(req: NextRequest): Promise<NextResponse | null> {
  if (!ottStorefrontLive()) return null;
  const host = req.headers.get("host") ?? "";
  if (!isCustomHost(host)) return null;
  const handle = await handleForHost(host, resolveCustomDomain);
  if (!handle) return null;
  const url = req.nextUrl.clone();
  url.pathname = rewritePath(handle, req.nextUrl.pathname);
  return NextResponse.rewrite(url);
}

const clerkHandler = clerkMiddleware(
  async (auth, req) => {
    if (isPublicRoute(req)) return;
    if (isSignUpFirstRoute(req)) {
      await auth.protect({ unauthenticatedUrl: signUpRedirectUrl(req) });
      return;
    }
    if (isProtectedRoute(req)) {
      await auth.protect();
    }
  },
  // Only when NEXT_PUBLIC_CLERK_PROXY_URL is set (lib/clerk.ts); otherwise
  // Clerk uses the FAPI domain encoded in the publishable key.
  clerkProxyUrl ? { proxyUrl: clerkProxyUrl } : undefined,
);

/**
 * When no real Clerk instance is configured (placeholder/absent publishable
 * key — see lib/clerk.ts), auth is non-functional by design: skip Clerk
 * entirely and let every route through. This keeps the public marketing site
 * fully working (no dependency on a live Clerk backend) until a real key is
 * added, at which point protection re-engages automatically.
 */
export default async function middleware(
  req: NextRequest,
  event: Parameters<typeof clerkHandler>[1],
) {
  // www.menivor.com is routed to this same Worker (wrangler.jsonc) but never
  // redirected to the apex, so it served a full 200 duplicate of every page
  // (SEO audit, 2026-10-19). 301 it to the canonical apex host.
  if (req.nextUrl.hostname === "www.menivor.com") {
    const target = new URL(req.nextUrl.toString());
    target.hostname = "menivor.com";
    return NextResponse.redirect(target, 301);
  }
  // /tr and /es 404 even though the UI supports those locales (switched
  // client-side, not via a path segment) — there's no real indexable page at
  // those paths yet, so redirect instead of dead-ending visitors/crawlers
  // who land there expecting a localized page (SEO audit, 2026-10-19).
  if (req.nextUrl.pathname === "/tr" || req.nextUrl.pathname === "/es") {
    return NextResponse.redirect(new URL("/", req.nextUrl), 302);
  }
  const custom = await customDomainRewrite(req);
  if (custom) return custom;
  if (!hasRealClerkKey) {
    return NextResponse.next();
  }
  // Clerk Frontend API proxy: forward /__clerk/* to frontend-api.clerk.dev
  // (lib/clerk-proxy.ts). Inert until NEXT_PUBLIC_CLERK_PROXY_URL points the
  // browser here, but always live so Clerk can validate the proxy before the
  // switch. Needs the CLERK_SECRET_KEY Worker secret.
  if (isClerkProxyPath(req.nextUrl.pathname)) {
    return proxyClerkRequest(req, {
      secretKey: process.env.CLERK_SECRET_KEY ?? "",
      proxyUrl: clerkProxyUrl || undefined,
    });
  }
  return clerkHandler(req, event);
}

export const config = {
  matcher: [
    // Run on everything except Next.js internals and static files,
    // unless present in search params.
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    // Always run for API routes.
    "/(api|trpc)(.*)",
    // Clerk auto-proxy (Frontend API is proxied under /__clerk on the app's
    // own domain); the middleware must run so these requests reach Clerk.
    "/__clerk/:path*",
  ],
};
