"use client";

import * as React from "react";
import { Bot, Check, MessageSquare } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import {
  askAgent,
  decideProposal,
  disconnectSlack,
  installSlack,
  listProposals,
  proposeChanges,
  type AgentAnswer,
  type Proposal,
} from "../_lib/api";
import type { SectionProps } from "./AdAccountsSection";

/** The Ads agent: onboarding credits, a small Q&A panel, proposals to approve, and Slack. */
export function AgentSection({ data, scope, getToken, onChanged }: SectionProps) {
  const { agent, slack } = data;
  const [question, setQuestion] = React.useState("");
  const [answer, setAnswer] = React.useState<AgentAnswer | null>(null);
  const [proposals, setProposals] = React.useState<readonly Proposal[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const token = React.useCallback(async () => ({ token: (await getToken()) ?? "" }), [getToken]);

  const loadProposals = React.useCallback(async () => {
    if (!agent.plan_allows) return;
    try {
      setProposals(await listProposals(scope, await token()));
    } catch {
      setProposals([]);
    }
  }, [agent.plan_allows, scope, token]);

  React.useEffect(() => {
    void loadProposals();
  }, [loadProposals]);

  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await work();
    } catch (err) {
      setError(friendlyErrorMessage(err, "That did not work. Try again."));
    } finally {
      setBusy(false);
    }
  };

  const ask = (event: React.FormEvent) => {
    event.preventDefault();
    if (!question.trim()) return;
    void run(async () => {
      setAnswer(await askAgent(question, scope, await token()));
      onChanged();
    });
  };

  const decide = (id: string, decision: "approve" | "reject") =>
    run(async () => {
      await decideProposal(id, decision, scope, await token());
      await loadProposals();
      onChanged();
    });

  return (
    <section aria-labelledby="ads-agent" className="space-y-4">
      <div>
        <h2 id="ads-agent" className="flex items-center gap-2 text-xl font-semibold">
          <Bot className="size-5 text-primary" aria-hidden />
          {agent.name}
        </h2>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          Ask about your campaigns, pull reports and get suggested changes. Nothing changes on an ad platform until a
          person approves it.
        </p>
      </div>

      <Card>
        <CardContent className="p-5">
          <h3 className="text-sm font-semibold">Get started</h3>
          <ol className="mt-3 space-y-2 text-sm">
            {agent.onboarding.steps.map((step) => (
              <li key={step.key} className="flex items-center justify-between gap-3">
                <span className="flex items-center gap-2">
                  <span className={`flex size-5 items-center justify-center rounded-full border ${
                    step.done ? "border-success/40 bg-success/15 text-success" : "border-white/15"}`}>
                    {step.done ? <Check className="size-3" aria-hidden /> : null}
                  </span>
                  {step.label}
                </span>
                <Badge variant={step.done ? "success" : "outline"}>+{step.credits} credits</Badge>
              </li>
            ))}
          </ol>
        </CardContent>
      </Card>

      {!agent.plan_allows ? (
        <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">
          {agent.plan_message}
        </p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardContent className="space-y-3 p-5">
              <form onSubmit={ask} className="space-y-3">
                <label htmlFor="agent-question" className="text-sm font-semibold">Ask about your ads</label>
                <Textarea
                  id="agent-question"
                  rows={3}
                  maxLength={1000}
                  value={question}
                  placeholder="Which creative should I cut this week?"
                  onChange={(event) => setQuestion(event.target.value)}
                />
                <Button type="submit" disabled={busy || !question.trim()}>Ask</Button>
              </form>
              {answer ? <p className="whitespace-pre-line text-sm">{answer.answer}</p> : null}
            </CardContent>
          </Card>

          <Card>
            <CardContent className="space-y-3 p-5">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-semibold">Waiting for approval</h3>
                <Button variant="outline" size="sm" disabled={busy}
                  onClick={() => void run(async () => { await proposeChanges(scope, await token()); await loadProposals(); })}>
                  Suggest changes
                </Button>
              </div>
              {proposals.length === 0 ? (
                <p className="text-sm text-muted-foreground">No changes are waiting.</p>
              ) : (
                <ul className="space-y-3">
                  {proposals.map((item) => (
                    <li key={item.id} className="rounded-lg border border-white/[0.08] p-3 text-sm">
                      <p className="font-medium">{item.title}</p>
                      <p className="mt-1 text-xs text-muted-foreground">{item.payload.reason || item.summary}</p>
                      <div className="mt-2 flex gap-2">
                        <Button size="sm" disabled={busy} onClick={() => void decide(item.id, "approve")}>Approve</Button>
                        <Button size="sm" variant="ghost" disabled={busy} onClick={() => void decide(item.id, "reject")}>
                          Reject
                        </Button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      <Card>
        <CardContent className="flex flex-wrap items-center justify-between gap-3 p-5">
          <div>
            <h3 className="flex items-center gap-2 font-semibold">
              <MessageSquare className="size-4" aria-hidden />
              Slack
            </h3>
            <p className="text-xs text-muted-foreground">
              {slack.connected
                ? `Connected to ${slack.team_name ?? "Slack"}. Use ${slack.command} or mention the app.`
                : "Ask questions and approve changes from Slack. Pro and above."}
            </p>
          </div>
          {slack.connected ? (
            <Button variant="outline" size="sm" disabled={busy || !data.ads.can_manage}
              onClick={() => void run(async () => { await disconnectSlack(scope, await token()); onChanged(); })}>
              Disconnect
            </Button>
          ) : !slack.plan_allows || !slack.configured ? (
            <span className="text-xs text-muted-foreground">
              {slack.plan_allows ? "Coming soon" : "Upgrade to Pro"}
            </span>
          ) : (
            <Button size="sm" disabled={busy || !data.ads.can_manage}
              onClick={() => void run(async () => {
                const { authorize_url } = await installSlack(scope, await token());
                window.location.assign(authorize_url);
              })}>
              Add to Slack
            </Button>
          )}
        </CardContent>
      </Card>
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    </section>
  );
}
