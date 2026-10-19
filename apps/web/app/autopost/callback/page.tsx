import { Suspense } from "react";

import { AutopostShell, ConnectCallback } from "@/src/features/autopost";

export const metadata = { title: "Connecting" };

export default function AutopostCallbackPage() {
  return (
    <AutopostShell title="Connecting" subtitle="One moment while the account is added.">
      <Suspense fallback={null}>
        <ConnectCallback />
      </Suspense>
    </AutopostShell>
  );
}
