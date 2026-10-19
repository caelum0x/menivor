import Link from "next/link";
import { PlaySquare } from "lucide-react";
import { ottStorefrontLive } from "./flags";

/** "Watch the channel" link on a creator profile; renders nothing until the storefront is live. */
export function ChannelLink({ handle, live = ottStorefrontLive() }: Readonly<{ handle: string; live?: boolean }>) {
  const clean = handle.trim().replace(/^@/, "");
  if (!live || !clean) return null;
  return (
    <Link
      href={`/c/${encodeURIComponent(clean)}`}
      className="inline-flex items-center gap-2 rounded-full border border-border px-4 py-2 text-sm font-medium hover:bg-muted"
    >
      <PlaySquare className="size-4" aria-hidden />
      Watch the channel
    </Link>
  );
}
