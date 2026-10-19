import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowRight, Clapperboard, Play } from "lucide-react";
import { getPublicShare } from "@/lib/api";
import type { SharePublic } from "@/lib/types";
import { MenivorMark } from "@/components/brand/MenivorMark";

/**
 * PUBLIC watermarked share page (`/r/{token}`). Rendered for logged-out visitors
 * (forced public in `middleware.ts`), it fetches the STRICT safe DTO from
 * GET /public/r/{token} ANONYMOUSLY (no Clerk token, no app key) and shows ONLY
 * the reel's title, a WATERMARKED preview, and a sign-up CTA that carries the
 * sharer's referral code. It NEVER attempts to show the clean (un-watermarked)
 * result, the owner id, view counts, or any financial — those fields are not
 * even present in {@link SharePublic}.
 */

interface SharePageProps {
  /** Next.js 15 passes dynamic route params as a Promise. */
  params: Promise<{ token: string }>;
}

/** Copy shown to a viewer regardless of which reel they landed on. */
const SHARE_DESCRIPTION =
  "Watch this UGC avatar reel made with Menivor — then make your own in minutes.";

/** Resolve a token to its safe public DTO, or `null` when it is gone/revoked. */
async function loadShare(token: string): Promise<SharePublic | null> {
  try {
    return await getPublicShare(token);
  } catch {
    return null;
  }
}

/** Build the sign-up CTA href, attributing the signup to the sharer when known. */
function signupHref(referralCode: string): string {
  const code = referralCode.trim();
  return code ? `/sign-up?ref=${encodeURIComponent(code)}` : "/sign-up";
}

export async function generateMetadata({
  params,
}: SharePageProps): Promise<Metadata> {
  const { token } = await params;
  const share = await loadShare(token);

  if (!share) {
    // Unknown / revoked link — don't index and don't leak anything.
    return {
      title: "Shared reel",
      description: SHARE_DESCRIPTION,
      robots: { index: false, follow: false },
    };
  }

  const title = share.title.trim() || "A reel made with Menivor";
  const video = share.watermarked_preview_url;

  return {
    title,
    description: SHARE_DESCRIPTION,
    openGraph: {
      title,
      description: SHARE_DESCRIPTION,
      siteName: "Menivor",
      type: "video.other",
      ...(video ? { videos: [{ url: video }] } : {}),
    },
    twitter: video
      ? {
          card: "player",
          title,
          description: SHARE_DESCRIPTION,
          players: [
            {
              playerUrl: video,
              streamUrl: video,
              width: 720,
              height: 1280,
            },
          ],
        }
      : {
          card: "summary_large_image",
          title,
          description: SHARE_DESCRIPTION,
        },
  };
}

export default async function SharePage({ params }: SharePageProps) {
  const { token } = await params;
  const share = await loadShare(token);
  if (!share) notFound();

  const title = share.title.trim() || "A reel made with Menivor";
  const previewUrl = share.watermarked_preview_url;
  const href = signupHref(share.sharer_referral_code);

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="border-b border-border/60">
        <div className="container flex h-16 items-center justify-between">
          <Link href="/" className="flex items-center gap-2 font-semibold">
            <MenivorMark variant="gradient" className="size-7" title="Menivor" />
          </Link>
          <Link
            href={href}
            className="text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            Make your own
          </Link>
        </div>
      </header>

      <main className="container flex flex-1 flex-col items-center justify-center py-12">
        <div className="grid w-full max-w-4xl items-center gap-10 lg:grid-cols-[minmax(0,320px)_1fr]">
          {/* Watermarked 9:16 preview — never the clean result. */}
          <figure className="mx-auto w-full max-w-xs">
            <div className="relative aspect-[9/16] overflow-hidden rounded-2xl border border-border bg-card shadow-lg">
              {previewUrl ? (
                <video
                  src={previewUrl}
                  controls
                  playsInline
                  preload="metadata"
                  className="h-full w-full bg-black object-contain"
                />
              ) : (
                <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-primary/40 via-card to-background">
                  <span className="flex size-12 items-center justify-center rounded-full bg-background/70 backdrop-blur">
                    <Play className="size-5 text-foreground" aria-hidden />
                  </span>
                </div>
              )}
            </div>
          </figure>

          <div className="text-center lg:text-left">
            <span className="inline-flex items-center gap-1 rounded-full border border-border px-2.5 py-0.5 text-xs font-medium text-muted-foreground">
              <Clapperboard className="size-3.5 text-primary" aria-hidden />
              Made with Menivor
            </span>
            <h1 className="mt-4 text-balance text-3xl font-bold tracking-tight sm:text-4xl">
              {title}
            </h1>
            <p className="mt-4 text-pretty text-muted-foreground">
              This is a watermarked preview. Create a free account to make your
              own UGC avatar reels — screen recording in, polished vertical video
              out.
            </p>

            <div className="mt-8 flex flex-col items-center gap-3 sm:flex-row lg:justify-start">
              <Link
                href={href}
                className="inline-flex h-12 items-center justify-center gap-2 rounded-md bg-primary px-6 text-base font-medium text-primary-foreground shadow transition-colors hover:bg-primary/90"
              >
                Make your own reel
                <ArrowRight className="size-4" aria-hidden />
              </Link>
              <Link
                href="/"
                className="inline-flex h-12 items-center justify-center rounded-md border border-border px-6 text-base font-medium transition-colors hover:bg-secondary/60"
              >
                How it works
              </Link>
            </div>

            {share.created_at ? (
              <p className="mt-6 text-xs text-muted-foreground">
                Shared {formatShareDate(share.created_at)}
              </p>
            ) : null}
          </div>
        </div>
      </main>

      <footer className="border-t border-border/60">
        <div className="container flex flex-col items-center justify-between gap-3 py-6 sm:flex-row">
          <span className="flex items-center gap-2 text-sm font-semibold">
            <MenivorMark className="size-4 text-primary" />
            Menivor
          </span>
          <span className="text-xs text-muted-foreground">
            &copy; {new Date().getFullYear()} Menivor
          </span>
        </div>
      </footer>
    </div>
  );
}

/** Format an ISO-8601 timestamp as a short, locale-stable date for the footer. */
function formatShareDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
