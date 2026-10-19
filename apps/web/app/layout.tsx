import type { Metadata, Viewport } from "next";
import Script from "next/script";
import { ClerkProvider } from "@clerk/nextjs";
import { clerkProxyUrl, hasRealClerkKey } from "@/lib/clerk";
import { clerkAppearance, clerkLocalization } from "@/lib/clerk-appearance";
import { I18nProvider } from "@/lib/i18n/context";
import { ApiSessionBridge } from "@/src/shared/api/ApiSessionBridge";
import { ClerkLoadGuard } from "@/src/shared/auth/ClerkLoadGuard";
import { GlitchTipInit } from "@/src/shared/observability";
import { StaffToolGuard } from "@/components/app-shell/StaffToolGuard";
import { getLocale } from "@/lib/i18n/server";
import { siteEntityGraph } from "@/lib/seo/entity";
import "./globals.css";

const SITE_URL = "https://menivor.com";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "Menivor: paste your App Store link, get a TikTok-ready demo video",
    template: "%s | Menivor",
  },
  description:
    "Paste your App Store or Google Play link and get three vertical demo reels with different hooks, an AI voiceover and word-by-word captions — ready to post.",
  keywords: [
    "AI short video generator",
    "faceless video generator",
    "link to video ad",
    "AI story video maker",
    "screen recording to video",
    "product link to video",
    "AI reels from a URL",
    "add captions to video",
    "AI video ads",
    "TikTok ad maker",
    "YouTube Shorts maker",
  ],
  applicationName: "Menivor",
  // Search Console and Bing Webmaster tokens come from the environment only;
  // when unset, no verification tag is rendered.
  verification: {
    google:
      process.env.NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION ||
      process.env.GOOGLE_SITE_VERIFICATION ||
      undefined,
    other: process.env.NEXT_PUBLIC_BING_SITE_VERIFICATION
      ? { "msvalidate.01": process.env.NEXT_PUBLIC_BING_SITE_VERIFICATION }
      : undefined,
  },
  alternates: {
    canonical: "/",
  },
  openGraph: {
    type: "website",
    url: SITE_URL,
    siteName: "Menivor",
    title: "Menivor: paste your App Store link, get a TikTok-ready demo video",
    description:
      "Paste your App Store or Google Play link and get three vertical demo reels with different hooks, an AI voiceover and word-by-word captions — ready to post.",
  },
  twitter: {
    card: "summary_large_image",
    title: "Menivor: paste your App Store link, get a TikTok-ready demo video",
    description:
      "Paste your App Store or Google Play link and get three vertical demo reels with different hooks, an AI voiceover and word-by-word captions.",
  },
};

// MB1: the entity graph (Organization, WebSite, SoftwareApplication) with
// offers read from plan config lives in lib/seo/entity.ts.
const STRUCTURED_DATA = siteEntityGraph();

export const viewport: Viewport = {
  themeColor: "#0a0a0b",
  width: "device-width",
  initialScale: 1,
};

/**
 * Render on-demand rather than statically prerendering at build time. When no
 * real Clerk instance is configured we intentionally omit <ClerkProvider>
 * (see below), so the authenticated app surface — which uses Clerk components
 * directly — cannot be prerendered. The public marketing pages are Clerk-free
 * (they use components/auth/clerk-safe) and render fine on-demand. Once a real
 * Clerk key is added, this can be relaxed back to static where desired.
 */
export const dynamic = "force-dynamic";

export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const locale = await getLocale();
  const shell = (
    <html
      lang={locale}
      suppressHydrationWarning
      className="scroll-smooth"
    >
      <body className="min-h-dvh bg-background font-sans text-foreground antialiased">
        {/* X conversion tracking base code */}
        <Script id="x-conversion-tracking-base" strategy="afterInteractive">
          {`!function(e,t,n,s,u,a){e.twq||(s=e.twq=function(){s.exe?s.exe.apply(s,arguments):s.queue.push(arguments);
},s.version='1.1',s.queue=[],u=t.createElement(n),u.async=!0,u.src='https://static.ads-twitter.com/uwt.js',
a=t.getElementsByTagName(n)[0],a.parentNode.insertBefore(u,a))}(window,document,'script');
twq('config','rhhqi');`}
        </Script>
        {/* End X conversion tracking base code */}
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(STRUCTURED_DATA) }}
        />
        <I18nProvider initialLocale={locale}>
          <ApiSessionBridge />
          <GlitchTipInit />
          {hasRealClerkKey && <ClerkLoadGuard />}
          <StaffToolGuard />
          {children}
        </I18nProvider>
      </body>
    </html>
  );

  // Only mount ClerkProvider when a real Clerk instance is configured. With a
  // placeholder/absent key, mounting it would make the browser load a dead
  // Frontend API (e.g. clerk.example.com) and break every page. The public
  // marketing site renders fully without it; auth surfaces stay dormant until a
  // real NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY is provided. See lib/clerk.ts.
  if (!hasRealClerkKey) {
    return shell;
  }

  return (
    <ClerkProvider
      proxyUrl={clerkProxyUrl || undefined}
      appearance={clerkAppearance}
      localization={clerkLocalization}
    >
      {shell}
    </ClerkProvider>
  );
}
