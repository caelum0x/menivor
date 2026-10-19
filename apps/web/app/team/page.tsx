import { redirect } from "next/navigation";

/**
 * `/team` is kept as a stable alias: team workspaces (members, invites,
 * credits and plan) live at the canonical `/workspace` page.
 */
export default function TeamPage(): never {
  redirect("/workspace");
}
