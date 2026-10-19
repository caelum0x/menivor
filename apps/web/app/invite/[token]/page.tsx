import type { Metadata } from "next";
import { AcceptInvitePage } from "@/src/features/invites/AcceptInvitePage";

export const metadata: Metadata = {
  title: "Workspace invite",
  robots: { index: false, follow: false },
};

export default function Page() {
  return <AcceptInvitePage />;
}
