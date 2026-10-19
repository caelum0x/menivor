import Link from "next/link";
import { UserButton } from "@/components/auth/clerk-safe";
import { BillingStatus } from "@/components/billing/BillingStatus";
import { MenivorMark } from "@/components/brand/MenivorMark";

export default function BillingCancelPage() {
  return (
    <main className="min-h-dvh">
      <header className="border-b border-border">
        <div className="container flex items-center justify-between py-4">
          <Link
            href="/reels"
            className="flex items-center gap-2 font-semibold"
          >
            <MenivorMark variant="gradient" className="size-7" title="Menivor" />
          </Link>
          <UserButton />
        </div>
      </header>

      <section className="container flex items-center justify-center py-20">
        <BillingStatus
          tone="cancel"
          title="Checkout canceled"
          description="No charge was made. Your credit balance is unchanged — you can pick a pack and try again whenever you're ready."
        />
      </section>
    </main>
  );
}
