import { UserButton } from "@/components/auth/clerk-safe";
import { Radio } from "lucide-react";

import { ChannelConsole } from "@/src/features/channel-console/ChannelConsole";

/** Channel console route — connected accounts, scheduling queue, A/B experiments. */
export default function ChannelsPage() {
  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Radio className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Channel console</h1>
        </div>
        <UserButton afterSignOutUrl="/" />
      </header>
      <p className="mb-6 text-sm text-muted-foreground">
        Manage connected accounts, queue finished reels to auto-publish, and run
        caption / thumbnail A/B tests to find the best-performing variant.
      </p>
      <ChannelConsole />
    </main>
  );
}
