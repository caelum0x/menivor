import type { Metadata } from "next";
import { FreeToolPage, freeToolMetadata } from "@/components/marketing/free-tools/FreeToolPage";

const SLUG = "tiktok-hook-generator";

export const metadata: Metadata = freeToolMetadata(SLUG);

export default function Page() {
  return <FreeToolPage slug={SLUG} />;
}
