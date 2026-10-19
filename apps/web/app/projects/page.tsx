import type { Metadata } from "next";
import { ProjectsPage } from "@/src/features/projects";

export const metadata: Metadata = {
  title: "Projects",
  description: "Everything you've made on Menivor — reels, edits, and AI clips in one place.",
};

export default function Page() {
  return <ProjectsPage />;
}
