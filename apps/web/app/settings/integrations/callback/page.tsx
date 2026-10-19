"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { finishCallback } from "../_lib/api";

function CallbackInner() {
  const params = useSearchParams();
  const router = useRouter();
  const getApiToken = useApiToken();
  const [message, setMessage] = React.useState("Finishing the connection...");
  const [failed, setFailed] = React.useState(false);
  const started = React.useRef(false);

  React.useEffect(() => {
    if (started.current) return;
    started.current = true;
    const code = params.get("code") || params.get("auth_code") || "";
    const state = params.get("state") || "";
    if (!code || !state) {
      setFailed(true);
      setMessage(params.get("error_description") || "The sign-in was cancelled.");
      return;
    }
    void (async () => {
      try {
        await finishCallback(code, state, { token: (await getApiToken()) ?? "" });
        router.replace("/settings/integrations");
      } catch (err) {
        setFailed(true);
        setMessage(friendlyErrorMessage(err, "The connection did not finish."));
      }
    })();
  }, [params, router, getApiToken]);

  return (
    <div className="space-y-4 text-center">
      <p className={failed ? "text-destructive" : "text-muted-foreground"} role={failed ? "alert" : "status"}>
        {message}
      </p>
      {failed ? (
        <Button asChild variant="outline" size="sm">
          <Link href="/settings/integrations">Back to Integrations</Link>
        </Button>
      ) : null}
    </div>
  );
}

/** OAuth return page for ad platforms and Slack: hands code + state to the API, then goes back. */
export default function IntegrationsCallbackPage() {
  return (
    <main className="container flex min-h-dvh items-center justify-center py-10">
      <React.Suspense fallback={<p className="text-muted-foreground">Finishing the connection...</p>}>
        <CallbackInner />
      </React.Suspense>
    </main>
  );
}
