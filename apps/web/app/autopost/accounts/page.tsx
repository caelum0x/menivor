import { AccountsScreen, AutopostShell } from "@/src/features/autopost";

export const metadata = { title: "Accounts" };

export default function AutopostAccountsPage() {
  return (
    <AutopostShell
      title="Accounts"
      subtitle="Connect the accounts you own. Each one posts at its own pace, inside the platform's limits."
    >
      <AccountsScreen />
    </AutopostShell>
  );
}
