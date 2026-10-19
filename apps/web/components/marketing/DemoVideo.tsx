import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * A REAL Menivor render (job e049f13062d0…, rendered by the production
 * pipeline at api.menivor.com from a voice memo + the quick-create flow —
 * no mockups). Override via env for a CDN-hosted replacement.
 */
export const MENIVOR_DEMO_VIDEO_URL =
  process.env.NEXT_PUBLIC_MENIVOR_DEMO_VIDEO_URL || "/demo/menivor-demo.mp4";
export const MENIVOR_DEMO_POSTER_URL =
  process.env.NEXT_PUBLIC_MENIVOR_DEMO_POSTER_URL ||
  "/demo/menivor-demo-poster.jpg";

/**
 * "See it in action" — plays the rendered reel in a phone-shaped frame next
 * to the claim it proves: voice memo in, word-timed karaoke captions out.
 */
export function DemoVideo() {
  return (
    <section className="border-b border-border">
      <div className="container grid items-center gap-12 py-16 lg:grid-cols-[minmax(0,1fr)_minmax(0,300px)] lg:gap-20">
        <div className="max-w-xl">
          <p className="kicker text-muted-foreground">a real render</p>
          <h2 className="mt-4 text-display font-bold">
            This reel was made from one voice memo.
          </h2>
          <p className="mt-4 text-pretty leading-relaxed text-muted-foreground">
            The video on the right came out of Menivor&rsquo;s production
            pipeline exactly as you see it: a short narration was uploaded,
            transcribed into word-timed karaoke captions, and composited over
            looping background footage as a 1080&times;1920 MP4 — in under a
            minute, with no editor open.
          </p>
          <div className="mt-6">
            <Button asChild size="lg">
              <Link href="/sign-up">
                Make yours free <ArrowRight className="size-4" />
              </Link>
            </Button>
          </div>
        </div>

        <div className="mx-auto w-full max-w-[280px] lg:mx-0">
          <div className="glass rounded-[2rem] p-2">
            <div className="overflow-hidden rounded-[1.5rem] border border-white/[0.08] bg-black">
              <video
                src={MENIVOR_DEMO_VIDEO_URL}
                poster={MENIVOR_DEMO_POSTER_URL}
                controls
                loop
                muted
                playsInline
                preload="metadata"
                className="aspect-[9/16] h-auto w-full"
                aria-label="A reel rendered by Menivor with word-timed karaoke captions"
              >
                Your browser does not support the video tag.
              </video>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
