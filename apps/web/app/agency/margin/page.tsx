import { UserButton } from "@/components/auth/clerk-safe";
import { Calculator } from "lucide-react";
import { MarginCalculator } from "@/src/features/agency/MarginCalculator";

export default function AgencyMarginPage() {
  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Calculator className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Margin</h1>
        </div>
        <UserButton afterSignOutUrl="/" />
      </header>
      <MarginCalculator />
    </main>
  );
}
