import type { Metadata } from "next";
import { Languages } from "lucide-react";
import { UserButton } from "@/components/auth/clerk-safe";

import { DubVideoStudio } from "@/src/features/dub-video";

export const metadata: Metadata = {
  title: "Dub a video",
  description:
    "Dub a video you uploaded into another language, with a translated voice track and subtitle files.",
};

/**
 * Studio sub-page: dub any uploaded video.
 *
 * Wired to the dub domain (`apps/api/app/domains/dub`):
 *   GET  /dub/options, POST /dub/videos, GET /dub/videos, GET /dub/videos/{id}
 */
export default function StudioDubPage() {
  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Languages className="h-6 w-6 text-primary" aria-hidden />
          <div>
            <h1 className="text-2xl font-semibold">Dub a video</h1>
            <p className="text-sm text-muted-foreground">
              Upload a video, pick the language to dub into, and get the dubbed video plus
              subtitle files. Free voices by default.
            </p>
          </div>
        </div>
        <UserButton afterSignOutUrl="/" />
      </header>
      <DubVideoStudio />
    </main>
  );
}
