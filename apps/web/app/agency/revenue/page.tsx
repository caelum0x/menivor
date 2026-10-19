import { UserButton } from "@/components/auth/clerk-safe";
import { TrendingUp } from "lucide-react";
import { RevenueSummary } from "@/src/features/agency/RevenueSummary";

export default function AgencyRevenuePage() {
  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Revenue</h1>
        </div>
        <UserButton afterSignOutUrl="/" />
      </header>
      <RevenueSummary />
    </main>
  );
}
