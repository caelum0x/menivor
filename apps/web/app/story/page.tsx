import type { Metadata } from "next";
import { Story8Panel } from "@/src/features/story8";

export const metadata: Metadata = {
  title: "Story in 8 frames",
  description: "Type a topic or paste a script and get an eight-frame vertical story, voiced and captioned.",
};

export default function StoryPage() {
  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <h1 className="mb-2 text-2xl font-semibold">Story in 8 frames</h1>
      <p className="mb-6 text-sm text-muted-foreground">
        Eight frames with the same main character, a voice and word-by-word captions. You see the price before anything starts.
      </p>
      <Story8Panel />
    </main>
  );
}
