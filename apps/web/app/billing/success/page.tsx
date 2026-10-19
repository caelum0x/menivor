import Link from "next/link";
import { UserButton } from "@/components/auth/clerk-safe";
import { BillingStatus } from "@/components/billing/BillingStatus";
import { MenivorMark } from "@/components/brand/MenivorMark";

export default function BillingSuccessPage() {
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
          tone="success"
          title="Payment successful"
          description="Thanks for your purchase! We are confirming the payment with the provider — your balance below updates automatically."
        />
      </section>
    </main>
  );
}
