import { UserButton } from "@/components/auth/clerk-safe";
import { Building2 } from "lucide-react";
import { ClientDetail } from "@/src/features/agency/ClientDetail";

export default async function ClientDetailPage({
  params,
}: {
  params: Promise<{ clientId: string }>;
}) {
  const { clientId } = await params;
  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Building2 className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Client</h1>
        </div>
        <UserButton afterSignOutUrl="/" />
      </header>
      <ClientDetail clientId={clientId} />
    </main>
  );
}
