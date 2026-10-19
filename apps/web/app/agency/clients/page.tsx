import { UserButton } from "@/components/auth/clerk-safe";
import { Building2 } from "lucide-react";
import { AgencyClients } from "@/src/features/agency/AgencyClients";

export default function AgencyClientsPage() {
  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Building2 className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Clients</h1>
        </div>
        <UserButton afterSignOutUrl="/" />
      </header>
      <AgencyClients />
    </main>
  );
}
