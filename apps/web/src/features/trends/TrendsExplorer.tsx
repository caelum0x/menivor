"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { Loader2, TrendingUp } from "lucide-react";

import { ApiError } from "@/src/shared/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { parseTrendLines, rankTrends, type RankedTrend } from "./api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

const PLACEHOLDER = [
  "dance-loop: 100,400,1200,3000",
  "cooking-asmr: 5000,5200,5100,4800",
  "ai-avatar: 50,90,240,900",
].join("\n");

/** Paste trend counts, rank them by opportunity + phase. */
export function TrendsExplorer() {
  const { getToken } = useAuth();
  const [text, setText] = React.useState("");
  const [ranked, setRanked] = React.useState<RankedTrend[]>([]);
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  const onRank = React.useCallback(async () => {
    setBusy(true);
    setError("");
    const trends = parseTrendLines(text);
    if (trends.length === 0) {
      setError('Paste at least one line like "trend_id: 100,400,1200".');
      setBusy(false);
      return;
    }
    try {
      const token = (await getToken()) ?? undefined;
      const res = await rankTrends({ trends, limit: 50 }, { token });
      setRanked(res.trends);
    } catch (err) {
      setError(friendlyErrorMessage(err, "Failed to rank."));
    } finally {
      setBusy(false);
    }
  }, [text, getToken]);

  return (
    <div className="space-y-6">
      <Card>
        <CardContent className="space-y-3 py-5">
          <div className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-primary" aria-hidden />
            <h2 className="font-semibold">Rank trends</h2>
          </div>
          <p className="text-xs text-muted-foreground">
            One trend per line: <code>trend_id: 100,400,1200,3000</code> (counts oldest → newest).
          </p>
          <Textarea
            rows={6}
            placeholder={PLACEHOLDER}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <Button onClick={() => void onRank()} disabled={busy}>
            {busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden /> : null}
            Rank
          </Button>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </CardContent>
      </Card>

      {ranked.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {ranked.map((t) => (
            <Card key={t.trend_id}>
              <CardContent className="space-y-2 py-4">
                <div className="flex items-center justify-between gap-2">
                  <p className="truncate font-medium">{t.trend_id}</p>
                  {t.recommend ? (
                    <Badge variant="secondary">recommend</Badge>
                  ) : (
                    <Badge variant="outline">hold</Badge>
                  )}
                </div>
                <p className="text-2xl font-semibold text-primary">
                  {(t.opportunity * 100).toFixed(0)}%
                </p>
                <p className="text-xs text-muted-foreground">opportunity</p>
                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <span>phase</span>
                  <Badge variant="outline">{t.phase}</Badge>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
