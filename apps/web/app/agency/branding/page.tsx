import { UserButton } from "@/components/auth/clerk-safe";
import { Image as ImageIcon } from "lucide-react";
import { AgencyBranding } from "@/src/features/agency/AgencyBranding";

export default function AgencyBrandingPage() {
  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ImageIcon className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Branding</h1>
        </div>
        <UserButton afterSignOutUrl="/" />
      </header>
      <AgencyBranding />
    </main>
  );
}
