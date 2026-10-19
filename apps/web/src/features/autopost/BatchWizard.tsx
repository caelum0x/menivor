"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

import {
  createCampaign,
  getCreatorInfo,
  listAccounts,
  previewCampaign,
  type Account,
  type Preview,
} from "./api";
import { EMPTY_FORM, buildCampaignBody, postableAccounts, type BatchForm } from "./plan";
import { AccountsStep } from "./wizard/AccountsStep";
import { DetailsStep, type TikTokCreator } from "./wizard/DetailsStep";
import { ReviewStep } from "./wizard/ReviewStep";
import { VideosStep } from "./wizard/VideosStep";

const STEPS = ["videos", "accounts", "details", "review"] as const;
type Step = (typeof STEPS)[number];
const TITLES: Record<Step, string> = {
  videos: "Choose videos",
  accounts: "Choose accounts",
  details: "Write the post",
  review: "Check the schedule",
};

/** Batch flow: videos, then accounts, then the post, then the schedule. One action per step. */
export function BatchWizard() {
  const router = useRouter();
  const [step, setStep] = React.useState<Step>("videos");
  const [form, setForm] = React.useState<BatchForm>(EMPTY_FORM);
  const [accounts, setAccounts] = React.useState<Account[]>([]);
  const [tiktok, setTiktok] = React.useState<TikTokCreator[]>([]);
  const [preview, setPreview] = React.useState<Preview | null>(null);
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  const patch = React.useCallback((change: Partial<BatchForm>) => {
    setForm((prev) => ({ ...prev, ...change }));
  }, []);

  React.useEffect(() => {
    listAccounts()
      .then((res) => setAccounts(postableAccounts(res.accounts)))
      .catch((err) => setError(friendlyErrorMessage(err, "Could not load your accounts.")));
  }, []);

  const loadCreators = React.useCallback(async (ids: string[]) => {
    const chosen = accounts.filter((a) => ids.includes(a.id) && a.provider === "tiktok");
    const results = await Promise.all(
      chosen.map(async (a): Promise<TikTokCreator> => {
        try {
          return { accountId: a.id, info: await getCreatorInfo(a.id), error: "" };
        } catch (err) {
          return { accountId: a.id, info: null, error: friendlyErrorMessage(err, "Could not reach TikTok") };
        }
      }),
    );
    setTiktok(results);
  }, [accounts]);

  const index = STEPS.indexOf(step);

  const next = async () => {
    setError("");
    if (step === "videos") {
      if (form.jobIds.length === 0) return setError("Choose at least one video.");
      return setStep("accounts");
    }
    if (step === "accounts") {
      if (form.accountIds.length === 0) return setError("Choose at least one account.");
      setStep("details");
      await loadCreators(form.accountIds);
      return;
    }
    if (step === "details") {
      if (tiktok.some((t) => t.info === null)) {
        return setError("A TikTok account could not be checked. Reconnect it or leave it out.");
      }
      try {
        const body = buildCampaignBody(form);
        setPreview(null);
        setStep("review");
        setPreview(await previewCampaign(body));
      } catch (err) {
        setError(err instanceof Error && !("status" in err) ? err.message : friendlyErrorMessage(err));
        if (step === "details") setStep("details");
      }
      return;
    }
    setBusy(true);
    try {
      await createCampaign(buildCampaignBody(form));
      router.push("/autopost");
    } catch (err) {
      setError(friendlyErrorMessage(err, "Could not queue the posts."));
      setBusy(false);
    }
  };

  const primary =
    step === "review" ? `Queue ${preview?.posts.length ?? ""} posts`.replace("  ", " ") : "Continue";

  return (
    <Card>
      <CardContent className="space-y-6 p-6">
        <div>
          <p className="text-xs text-muted-foreground">
            Step {index + 1} of {STEPS.length}
          </p>
          <h2 className="text-xl font-semibold">{TITLES[step]}</h2>
        </div>

        {step === "videos" ? (
          <VideosStep selected={form.jobIds} onChange={(jobIds) => patch({ jobIds })} />
        ) : null}
        {step === "accounts" ? <AccountsStep accounts={accounts} form={form} onChange={patch} /> : null}
        {step === "details" ? <DetailsStep form={form} onChange={patch} tiktok={tiktok} /> : null}
        {step === "review" ? <ReviewStep preview={preview} error="" /> : null}

        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}

        <div className="flex items-center justify-between gap-3">
          <Button
            variant="ghost"
            onClick={() => {
              setError("");
              if (index === 0) router.push("/autopost");
              else setStep(STEPS[index - 1] ?? "videos");
            }}
            disabled={busy}
          >
            Back
          </Button>
          <Button onClick={() => void next()} disabled={busy || (step === "review" && !preview)}>
            {busy ? <Loader2 className="animate-spin" aria-hidden /> : null}
            {primary}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
