import type { Metadata } from "next";
import { Clapperboard } from "lucide-react";

import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { FilmPlanner } from "@/src/features/film/FilmPlanner";
import { FilmStudio } from "@/src/features/film/FilmStudio";

export const metadata: Metadata = {
  title: "Film studio",
  description:
    "Plan a character-consistent shot list, render every shot and export the finished film.",
};

/** Film / Series Studio route — plan, render shots, and export the final film. */
export default function FilmPage() {
  return (
    <main className="min-h-dvh">
      <AppTopBar />
      <section className="container max-w-6xl py-8">
        <div className="mb-2 flex items-center gap-2">
          <Clapperboard className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Film / Series Studio</h1>
        </div>
        <p className="mb-6 text-sm text-muted-foreground">
          Plan a character-consistent shot list, render each locked shot, then export every
          shot stitched into one final film.
        </p>
        <FilmStudio />

        <div className="mt-12">
          <h2 className="mb-1 text-lg font-semibold">Quick plan (preview)</h2>
          <p className="mb-4 text-sm text-muted-foreground">
            Turn beats and a lead character into an ordered, camera-ready shot list without
            saving anything.
          </p>
          <FilmPlanner />
        </div>
      </section>
    </main>
  );
}
