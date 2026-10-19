import { redirect } from "next/navigation";

/** /media → the gateway playground (the default entry point). */
export default function MediaIndexPage() {
  redirect("/media/playground");
}
