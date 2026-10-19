import { AccountPace, AutopostShell } from "@/src/features/autopost";

export const metadata = { title: "Account pace" };

export default async function AutopostAccountPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <AutopostShell title="Pace" subtitle="How often this account posts, and when.">
      <AccountPace accountId={id} />
    </AutopostShell>
  );
}
