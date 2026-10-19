import { redirect } from "next/navigation";

/** The job list is the canonical reel library at `/reels`. */
export default function JobsIndexPage(): never {
  redirect("/reels");
}
