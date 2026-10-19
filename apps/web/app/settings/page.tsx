import { redirect } from "next/navigation";

/** `/settings` has no content of its own: open the first settings tab. */
export default function SettingsIndexPage(): never {
  redirect("/settings/team");
}
