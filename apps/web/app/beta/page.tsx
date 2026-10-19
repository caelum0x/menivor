import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getLaunchPosture } from "@/src/shared/launch-posture/server";
import { BetaPanel } from "./_components/BetaPanel";

export const metadata: Metadata = {
  title: "Request early access",
  description:
    "Menivor is in a private beta. Request access with your email and what you want to make; approved emails sign in normally.",
  alternates: { canonical: "/beta" },
};

/**
 * Private-beta access request page, linked from every readiness-aware CTA.
 * Once the launch status reports public access with signup open, nobody needs
 * to request access, so visitors go straight to free signup.
 */
export default async function BetaPage() {
  const posture = await getLaunchPosture();
  if (posture.mode === "public") redirect("/sign-up");
  return (
    <section className="container py-16 lg:py-24">
      <div className="max-w-2xl">
        <p className="kicker text-muted-foreground">Private beta</p>
        <h1 className="mt-4 text-display font-bold text-foreground">Request early access</h1>
        <p className="mt-4 text-pretty leading-relaxed text-muted-foreground">
          Menivor is open to a small group while we bring render capacity online. Tell us
          your email and what you want to make. We approve requests by hand; once your
          email is approved you sign in normally with it.
        </p>
      </div>
      <div className="mt-10">
        <BetaPanel />
      </div>
    </section>
  );
}
