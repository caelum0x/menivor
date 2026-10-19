import type { Metadata } from "next";
import { UploadsPage } from "@/src/features/uploads/UploadsPage";

export const metadata: Metadata = {
  title: "Uploads",
  description: "Your uploaded recordings, voiceovers, photos and clips on Menivor.",
};

export default function Page() {
  return <UploadsPage />;
}
