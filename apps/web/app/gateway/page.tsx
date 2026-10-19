import { UserButton } from "@/components/auth/clerk-safe";
import { KeyRound } from "lucide-react";

import { GatewayConsole } from "@/src/features/gateway/GatewayConsole";

/** API-resale gateway route — mint, revoke, and quote provisioning keys. */
export default function GatewayPage() {
  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <KeyRound className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">API gateway</h1>
        </div>
        <UserButton afterSignOutUrl="/" />
      </header>
      <p className="mb-6 text-sm text-muted-foreground">
        Resell generation under your own keys — set a daily spend cap and a markup; billed only on success.
      </p>
      <GatewayConsole />
    </main>
  );
}
