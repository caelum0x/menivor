import Link from "next/link";
import { ArrowLeft, Radio } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ChannelsManager } from "@/components/calendar/ChannelsManager";

export const metadata = {
  title: "Channels - Telegram, Discord, Mastodon",
};

/** Connect and manage the free-API channels the calendar can post to and the inbox can read. */
export default function CalendarChannelsPage() {
  return (
    <main className="container max-w-4xl py-8">
      <Button asChild variant="ghost" size="sm" className="mb-4">
        <Link href="/calendar">
          <ArrowLeft className="size-4" aria-hidden /> Calendar
        </Link>
      </Button>
      <header className="mb-6 space-y-1">
        <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
          <Radio className="size-6 text-primary" aria-hidden />
          Channels
        </h1>
        <p className="text-sm text-muted-foreground">
          Telegram channels and groups, Discord channels and Mastodon accounts. Their APIs are free and need no
          platform review, so a connected channel works right away. Credentials are encrypted and never shown again.
        </p>
      </header>
      <ChannelsManager />
    </main>
  );
}
