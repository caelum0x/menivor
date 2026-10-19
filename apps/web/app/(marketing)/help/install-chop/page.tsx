import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Installing Chop",
  description: "How to open Chop, the Menivor editor, the first time on Mac, Windows and Linux.",
  alternates: { canonical: "/help/install-chop" },
  robots: { index: false, follow: true },
};

interface Step {
  readonly platform: string;
  readonly steps: readonly React.ReactNode[];
}

const STEPS: readonly Step[] = [
  {
    platform: "Mac",
    steps: [
      "Open the downloaded .dmg and drag Chop into Applications.",
      <>
        If macOS says the app can&apos;t be opened, open Terminal and run{" "}
        <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs">
          xattr -dr com.apple.quarantine /Applications/Chop.app
        </code>
        , then open Chop again.
      </>,
    ],
  },
  {
    platform: "Windows",
    steps: [
      "Run the installer.",
      "If SmartScreen appears, choose More info, then Run anyway.",
    ],
  },
  {
    platform: "Linux",
    steps: [
      "AppImage: make it executable (chmod +x) and double-click it.",
      "Or install the .deb / .rpm with your package manager.",
    ],
  },
];

/**
 * Install help for the current, not-yet-signed Chop builds. Linked only from
 * the /editor download flow when an installer is published.
 */
export default function InstallChopPage() {
  return (
    <div className="container max-w-2xl py-16 lg:py-20">
      <h1 className="text-3xl font-bold tracking-tight">Installing Chop</h1>
      <p className="mt-3 text-muted-foreground">
        Chop isn&apos;t signed by Apple or Microsoft yet, so your computer may ask
        you to confirm the first time you open it.
      </p>
      <div className="mt-10 space-y-8">
        {STEPS.map((group) => (
          <section key={group.platform}>
            <h2 className="text-lg font-semibold text-foreground">{group.platform}</h2>
            <ol className="mt-3 list-decimal space-y-2 pl-5 text-muted-foreground">
              {group.steps.map((step, index) => (
                <li key={index}>{step}</li>
              ))}
            </ol>
          </section>
        ))}
      </div>
      <p className="mt-12 text-sm text-muted-foreground">
        <Link href="/editor" className="underline underline-offset-4 hover:text-foreground">
          Back to Chop
        </Link>
      </p>
    </div>
  );
}
