import { UserButton } from "@/components/auth/clerk-safe";
import { KeyRound } from "lucide-react";
import { AgencyKeys } from "@/src/features/agency/AgencyKeys";

export default function AgencyKeysPage() {
  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <KeyRound className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Client keys</h1>
        </div>
        <UserButton afterSignOutUrl="/" />
      </header>
      <AgencyKeys />
    </main>
  );
}
