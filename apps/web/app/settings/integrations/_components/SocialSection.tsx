"use client";

import * as React from "react";
import Link from "next/link";
import { Share2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import { startSocialConnect } from "../_lib/api";
import type { SectionProps } from "./AdAccountsSection";

/** Social accounts: one per platform, shared by the workspace (reuses Autopost connections). */
export function SocialSection({ data, scope, getToken }: SectionProps) {
  const [busy, setBusy] = React.useState("");
  const [error, setError] = React.useState("");

  const connect = async (provider: string) => {
    setBusy(provider);
    setError("");
    try {
      const { authorize_url } = await startSocialConnect(provider, scope, { token: (await getToken()) ?? "" });
      window.location.assign(authorize_url);
    } catch (err) {
      setError(friendlyErrorMessage(err, "Could not start connecting."));
      setBusy("");
    }
  };

  return (
    <section aria-labelledby="social-accounts" className="space-y-4">
      <div>
        <h2 id="social-accounts" className="flex items-center gap-2 text-xl font-semibold">
          <Share2 className="size-5 text-primary" aria-hidden />
          Social accounts
        </h2>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          Publish finished videos straight from a project. One account per platform, shared by the workspace.
        </p>
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        {data.social.platforms.map((platform) => (
          <Card key={platform.provider}>
            <CardContent className="flex h-full flex-col gap-3 p-5">
              <div className="flex items-center justify-between gap-2">
                <h3 className="font-semibold">{platform.label}</h3>
                <Badge variant={platform.account ? "success" : "secondary"}>
                  {platform.account ? "Connected" : "Not connected"}
                </Badge>
              </div>
              <p className="text-sm text-muted-foreground">
                {platform.account ? `@${platform.account.handle}` : platform.ready ? "No account yet" : "Not available yet"}
              </p>
              <div className="mt-auto">
                {platform.account ? (
                  <Button asChild variant="outline" size="sm">
                    <Link href="/autopost/accounts">Manage</Link>
                  </Button>
                ) : !platform.ready ? null : (
                  <Button size="sm" disabled={!data.social.can_manage || busy !== ""}
                    onClick={() => void connect(platform.provider)}>
                    Connect
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    </section>
  );
}
