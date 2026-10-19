import Link from "next/link";
import { headers } from "next/headers";
import { Captions, Download, Droplets, Gift } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { NewsletterForm } from "@/components/marketing/NewsletterForm";
import { JsonLd } from "@/components/marketing/seo/JsonLd";
import { SITE_URL, graphDocument } from "@/lib/seo";
import {
  getLatestEditorRelease,
  platformFromUserAgent,
  primaryAsset,
  type EditorAsset,
  type EditorPlatform,
  type EditorRelease,
} from "@/lib/editor-releases";

export const CHOP_TITLE = "Chop — the free Menivor video editor";
export const CHOP_DESCRIPTION =
  "Chop is a free desktop video editor for Mac, Windows and Linux. No watermark, with captions and voiceover built in.";

/** Where the unsigned-build install steps live (linked only when a build exists). */
export const CHOP_INSTALL_HELP_PATH = "/help/install-chop";

interface Benefit {
  readonly Icon: LucideIcon;
  readonly title: string;
  readonly body: string;
}

const BENEFITS: readonly Benefit[] = [
  { Icon: Gift, title: "Free", body: "Edit and export without paying a thing." },
  { Icon: Droplets, title: "No watermark", body: "Your video leaves clean." },
  { Icon: Captions, title: "Captions and voiceover", body: "Built in, running right on your computer." },
];

const PLATFORM_NAMES: Readonly<Record<EditorPlatform, string>> = {
  macos: "Mac",
  windows: "Windows",
  linux: "Linux",
};

/** One installer per other platform, for the quiet "also on" line. */
function otherPlatforms(release: EditorRelease, primary: EditorAsset): readonly EditorAsset[] {
  const platforms = (["macos", "windows", "linux"] as const).filter((p) => p !== primary.platform);
  return platforms
    .map((platform) => primaryAsset({ ...release, assets: release.assets.filter((a) => a.platform === platform) }, platform))
    .filter((asset): asset is EditorAsset => asset !== null && asset.platform !== primary.platform);
}

function DownloadCta({ release, primary }: Readonly<{ release: EditorRelease; primary: EditorAsset }>) {
  const others = otherPlatforms(release, primary);
  return (
    <div className="flex flex-col items-center gap-3">
      <Button asChild size="lg" className="h-12 px-8 text-base">
        <a href={primary.url} rel="nofollow">
          <Download className="size-5" aria-hidden />
          Download for {PLATFORM_NAMES[primary.platform]}
        </a>
      </Button>
      <p className="text-sm text-muted-foreground">
        {others.length > 0 ? (
          <>
            Also for{" "}
            {others.map((asset, index) => (
              <span key={asset.url}>
                {index > 0 ? " and " : ""}
                <a href={asset.url} rel="nofollow" className="underline underline-offset-4 hover:text-foreground">
                  {PLATFORM_NAMES[asset.platform]}
                </a>
              </span>
            ))}
            .{" "}
          </>
        ) : null}
        <Link href={CHOP_INSTALL_HELP_PATH} className="underline underline-offset-4 hover:text-foreground">
          Help installing
        </Link>
      </p>
    </div>
  );
}

function ComingSoon() {
  return (
    <div className="glass flex w-full max-w-md flex-col items-center gap-2 rounded-2xl p-5 text-left">
      <NewsletterForm
        className="max-w-none"
        title="Coming soon — get notified"
        blurb="One email when Chop is ready to download."
        submitLabel="Notify me"
      />
    </div>
  );
}

/**
 * The /editor landing: one headline, one line, three benefits, one action.
 * The action is a Download button when a release with installers exists,
 * otherwise a get-notified email form.
 */
export async function ChopLanding() {
  const [release, requestHeaders] = await Promise.all([getLatestEditorRelease(), headers()]);
  const platform = platformFromUserAgent(requestHeaders.get("user-agent"));
  const primary = release ? primaryAsset(release, platform) : null;
  const jsonLd = graphDocument([
    {
      "@type": "SoftwareApplication",
      name: "Chop",
      applicationCategory: "MultimediaApplication",
      operatingSystem: "macOS, Windows, Linux",
      description: CHOP_DESCRIPTION,
      offers: { "@type": "Offer", price: "0", priceCurrency: "USD" },
      url: `${SITE_URL}/editor`,
      ...(release ? { softwareVersion: release.tag } : {}),
    },
  ]);

  return (
    <div className="container flex flex-col items-center py-20 text-center lg:py-28">
      <JsonLd data={jsonLd} />
      <p className="kicker text-muted-foreground">Chop — the Menivor editor</p>
      <h1 className="mt-4 max-w-3xl text-balance text-display-lg font-bold text-foreground">
        Cut it. Caption it. Post it.
      </h1>
      <p className="mt-5 max-w-xl text-pretty text-lg text-muted-foreground">
        The free desktop video editor for Mac, Windows and Linux.
      </p>

      <div className="mt-10 flex w-full justify-center">
        {release && primary ? <DownloadCta release={release} primary={primary} /> : <ComingSoon />}
      </div>

      <ul className="mt-16 grid w-full max-w-3xl gap-4 sm:grid-cols-3">
        {BENEFITS.map(({ Icon, title, body }) => (
          <li key={title} className="glass flex flex-col items-center gap-2 rounded-2xl px-5 py-6">
            <Icon className="size-6 text-primary" aria-hidden />
            <p className="font-semibold text-foreground">{title}</p>
            <p className="text-sm text-muted-foreground">{body}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
