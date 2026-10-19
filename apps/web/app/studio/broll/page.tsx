import { redirect } from "next/navigation";

/**
 * `/studio/broll` is an alias of the canonical B-roll library at
 * `/broll-library`; one library keeps navigation consistent.
 */
export default function StudioBrollPage(): never {
  redirect("/broll-library");
}
