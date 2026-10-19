"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";

import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

import { finishConnect } from "./api";

/** Where TikTok, Instagram and Google send the browser back after the creator approves. */
export function ConnectCallback() {
  const params = useSearchParams();
  const router = useRouter();
  const [message, setMessage] = React.useState("Finishing the connection");
  const [failed, setFailed] = React.useState(false);
  const started = React.useRef(false);

  React.useEffect(() => {
    if (started.current) return;
    started.current = true;
    const code = params.get("code") ?? "";
    const state = params.get("state") ?? "";
    const denied = params.get("error") || params.get("error_reason");
    if (denied || !code || !state) {
      setFailed(true);
      setMessage(denied ? "The connection was not approved." : "This link is missing its details.");
      return;
    }
    void (async () => {
      try {
        await finishConnect(code, state);
        router.replace("/autopost/accounts");
      } catch (err) {
        setFailed(true);
        setMessage(friendlyErrorMessage(err, "Could not finish connecting. Start again."));
      }
    })();
  }, [params, router]);

  return (
    <div className="space-y-3 text-sm" role="status">
      <p className="flex items-center gap-2">
        {failed ? null : <Loader2 className="size-4 animate-spin" aria-hidden />}
        {message}
      </p>
      {failed ? (
        <Link href="/autopost/accounts" className="text-primary underline-offset-4 hover:underline">
          Back to accounts
        </Link>
      ) : null}
    </div>
  );
}
