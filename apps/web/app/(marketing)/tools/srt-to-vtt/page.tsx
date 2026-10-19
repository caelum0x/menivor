import type { Metadata } from "next";
import { FreeToolPage, freeToolMetadata } from "@/components/marketing/free-tools/FreeToolPage";

const SLUG = "srt-to-vtt";

export const metadata: Metadata = freeToolMetadata(SLUG);

export default function Page() {
  return <FreeToolPage slug={SLUG} />;
}
