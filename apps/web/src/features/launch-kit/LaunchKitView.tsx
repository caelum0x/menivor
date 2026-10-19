"use client";

/**
 * Launch Kit (Menivor Growth phase 3): first-100-users tooling — the
 * platform checklist, pain-point thread finder, competitor backlinks, and
 * the 10-step launch playbook. Backend: `app.domains.launch_kit` (HTTP
 * under `/launch-kit/*`). This view only calls those plain HTTP routes,
 * the same way `keyword-tracker`'s view does — MCP is a separate surface
 * for agent/tool callers, not the web client.
 */

import * as React from "react";
import Link from "next/link";
import { Rocket } from "lucide-react";
import { useAuth } from "@/components/auth/clerk-safe";
import { signInHref } from "@/lib/auth-redirect";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getStoredDeviceApiKey } from "@/src/shared/device/session";
import { PlatformChecklist } from "./PlatformChecklist";
import { PainPointFinder } from "./PainPointFinder";
import { CompetitorBacklinks } from "./CompetitorBacklinks";
import { LaunchChecklist } from "./LaunchChecklist";

type GateState = "loading" | "ready" | "signed_out";

const LAUNCH_KIT_PATH = "/launch-kit";

export function LaunchKitView() {
  const { isLoaded, isSignedIn } = useAuth();
  const [state, setState] = React.useState<GateState>("loading");
  const [productName, setProductName] = React.useState("");

  React.useEffect(() => {
    if (!isLoaded) return;
    if (!isSignedIn && !getStoredDeviceApiKey()) {
      setState("signed_out");
      return;
    }
    setState("ready");
  }, [isLoaded, isSignedIn]);

  if (state === "loading") return null;

  if (state === "signed_out") {
    return (
      <section className="glass-strong mx-auto max-w-xl rounded-3xl p-8 text-center">
        <Rocket className="mx-auto size-10 text-primary" aria-hidden />
        <h2 className="mt-4 text-2xl font-semibold tracking-tight">Sign in for your launch kit</h2>
        <Button asChild size="lg" className="neu-primary mt-6">
          <Link href={signInHref(LAUNCH_KIT_PATH)}>Sign in</Link>
        </Button>
      </section>
    );
  }

  return (
    <div className="space-y-6">
      <section className="glass rounded-2xl p-5">
        <Label htmlFor="launch-kit-product">Product</Label>
        <p className="mb-2 text-sm text-muted-foreground">
          Tracks platform submissions and the 10-step checklist for one product at a time.
        </p>
        <Input
          id="launch-kit-product"
          placeholder="Product name (e.g. Menivor)"
          value={productName}
          onChange={(e) => setProductName(e.target.value)}
        />
      </section>

      <PlatformChecklist productName={productName} />
      <PainPointFinder productName={productName} />
      <CompetitorBacklinks />
      <LaunchChecklist productName={productName} />

      <p className="text-center text-xs text-muted-foreground">
        The directory list, checklist, and backlink lookup behind this page are open source:{" "}
        <a
          href="https://github.com/caelum0x/launchmaxxing"
          target="_blank"
          rel="noopener noreferrer"
          className="underline underline-offset-2 hover:text-foreground"
        >
          launchmaxxing
        </a>{" "}
        is a free local CLI version of this same toolkit.
      </p>
    </div>
  );
}
