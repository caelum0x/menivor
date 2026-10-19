import type { Metadata } from "next";
import Link from "next/link";
import {
  PRESS_DESCRIPTION_LONG,
  PRESS_DESCRIPTION_SHORT,
  SUPPORT_EMAIL,
} from "@/lib/seo/entity";
import { LOGO_FILES, SAMPLE_REELS } from "./assets";

export const metadata: Metadata = {
  title: "Press kit",
  description: "Menivor logos, sample reels and approved descriptions for press and directories.",
  alternates: { canonical: "/press" },
};

export default function PressPage() {
  return (
    <div className="container py-16 lg:py-24">
      <div className="max-w-3xl">
        <p className="kicker text-muted-foreground">Press</p>
        <h1 className="mt-4 text-display-lg font-bold">Press kit</h1>
        <p className="mt-4 text-pretty text-lg leading-relaxed text-muted-foreground">
          Logos, sample reels and the descriptions we use everywhere. Questions go to{" "}
          <a
            href={`mailto:${SUPPORT_EMAIL}?subject=${encodeURIComponent("[Press] ")}`}
            className="font-medium text-primary underline underline-offset-4"
          >
            {SUPPORT_EMAIL}
          </a>
          .
        </p>

        <section className="mt-12 space-y-3">
          <h2 className="text-2xl font-semibold">Short description</h2>
          <p className="text-muted-foreground">{PRESS_DESCRIPTION_SHORT}</p>
        </section>

        <section className="mt-10 space-y-3">
          <h2 className="text-2xl font-semibold">Long description</h2>
          <p className="text-muted-foreground">{PRESS_DESCRIPTION_LONG}</p>
        </section>

        <section className="mt-12 space-y-3">
          <h2 className="text-2xl font-semibold">Logos</h2>
          <ul className="grid gap-3 sm:grid-cols-2">
            {LOGO_FILES.map((file) => (
              <li key={file.href}>
                <a
                  href={file.href}
                  download
                  className="flex items-center gap-3 rounded-lg border border-border p-4 transition-colors hover:border-primary/60"
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={file.href} alt="" width={40} height={40} className="h-10 w-10" />
                  <span>{file.label}</span>
                </a>
              </li>
            ))}
          </ul>
        </section>

        <section className="mt-12 space-y-3">
          <h2 className="text-2xl font-semibold">Sample reels</h2>
          <p className="text-muted-foreground">
            Real renders from the Menivor pipeline: a typed script, a neural voice and word captions over
            licensed stock footage. The businesses shown are examples.
          </p>
          <ul className="grid gap-4 sm:grid-cols-3">
            {SAMPLE_REELS.map((reel) => (
              <li key={reel.slug} className="space-y-2">
                <video
                  src={`/samples/showcase/${reel.slug}.mp4`}
                  poster={`/samples/showcase/${reel.slug}-poster.jpg`}
                  controls
                  preload="none"
                  playsInline
                  className="aspect-[9/16] w-full rounded-lg border border-border bg-black"
                />
                <a
                  href={`/samples/showcase/${reel.slug}.mp4`}
                  download
                  className="text-sm font-medium text-primary underline underline-offset-4"
                >
                  {reel.title} (MP4)
                </a>
              </li>
            ))}
          </ul>
        </section>

        <p className="mt-12 text-sm text-muted-foreground">
          More about the product on the{" "}
          <Link href="/about" className="text-primary underline underline-offset-4">
            about page
          </Link>
          .
        </p>
      </div>
    </div>
  );
}
