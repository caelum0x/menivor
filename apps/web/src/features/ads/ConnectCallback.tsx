"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { ErrorText, errorMessage, useRequestOptions } from "@/src/features/ad-studio/shared";
import { finishConnect, type AdsPlatform } from "./api";

/** OAuth return page: hand the code + state to the API, then go back to /ads. */
export function ConnectCallback({
  platform,
  code,
  state,
  denied,
}: {
  platform: AdsPlatform;
  code: string;
  state: string;
  denied: string;
}) {
  const router = useRouter();
  const requestOptions = useRequestOptions();
  const [error, setError] = React.useState(denied ? "The connection was cancelled." : "");
  const started = React.useRef(false);

  React.useEffect(() => {
    if (started.current || denied) return;
    started.current = true;
    if (!code || !state) {
      setError("The platform did not send an authorization code. Start the connection again.");
      return;
    }
    (async () => {
      try {
        await finishConnect(platform, { code, state }, await requestOptions());
        router.replace("/ads");
      } catch (err) {
        setError(errorMessage(err));
      }
    })();
  }, [platform, code, state, denied, requestOptions, router]);

  return (
    <div className="space-y-3">
      {error ? (
        <>
          <ErrorText message={error} />
          <Link href="/ads" className="text-sm text-primary underline">
            Back to paid ads
          </Link>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">Connecting your ad account...</p>
      )}
    </div>
  );
}
