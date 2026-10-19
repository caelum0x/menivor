import { redirect } from "next/navigation";

/** The admin index redirects to the first resource (users). */
export default function AdminIndexPage() {
  redirect("/admin/users");
}
