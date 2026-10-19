import { AutopostShell, BatchWizard } from "@/src/features/autopost";

export const metadata = { title: "New batch" };

export default function AutopostNewPage() {
  return (
    <AutopostShell
      title="New batch"
      subtitle="Pick videos, pick accounts, and Menivor spreads the posts out for you."
    >
      <BatchWizard />
    </AutopostShell>
  );
}
